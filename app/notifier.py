import logging
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from config import settings
from database import AsyncSessionLocal
from models import AlertFeedback, SmellAlert, SmellSighting, Vessel, VesselPortVisit
from smell_estimator import calculate_risk
from vessel_tracker import get_docked_vessels
from wind_checker import fetch_hourly_forecast, get_latest_wind

logger = logging.getLogger(__name__)

_application: Application | None = None


def get_application() -> Application:
    global _application
    if _application is None:
        _application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        _application.add_handler(CallbackQueryHandler(_handle_feedback, pattern=r"^feedback:"))
        _application.add_handler(CallbackQueryHandler(_handle_vessel_confirm, pattern=r"^smell_vessel:"))
        _application.add_handler(CommandHandler("start", _handle_start_command))
        _application.add_handler(CommandHandler("help", _handle_help_command))
        _application.add_handler(CommandHandler("smell", _handle_smell_command))
        _application.add_handler(CommandHandler("status", _handle_status_command))
        _application.add_handler(CommandHandler("forecast", _handle_forecast_command))
        _application.add_handler(CommandHandler("history", _handle_history_command))
    return _application


_VALID_FEEDBACK_TYPES = {"confirmed", "false_positive"}


async def _handle_feedback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()

    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "feedback":
        return

    _, feedback_type, alert_id_str = parts

    if feedback_type not in _VALID_FEEDBACK_TYPES:
        return

    try:
        alert_id = int(alert_id_str)
    except ValueError:
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AlertFeedback)
            .where(AlertFeedback.alert_id == alert_id)
            .order_by(desc(AlertFeedback.id))
            .limit(1)
        )
        existing = result.scalars().first()
        if existing:
            existing.feedback_type = feedback_type
            existing.reported_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            session.add(AlertFeedback(
                alert_id=alert_id,
                feedback_type=feedback_type,
                reported_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
        await session.commit()

    emoji = "✅" if feedback_type == "confirmed" else "❌"
    label = "Запах подтверждён" if feedback_type == "confirmed" else "Ложная тревога"
    try:
        await query.edit_message_text(f"{query.message.text}\n\n{emoji} {label}")
    except Exception:
        pass

    logger.info(f"Feedback '{feedback_type}' recorded for alert {alert_id_str}")


async def _handle_start_command(update: Update, context) -> None:
    await update.message.reply_text(
        "👋 Привет! Я *Нюхослав* — слежу за танкерами в порту и предупреждаю, "
        "когда ветер может принести запах нефти к тебе домой.\n\n"
        "Получай автоматические тревоги и используй /help для списка команд.",
        parse_mode="Markdown",
    )


async def _handle_help_command(update: Update, context) -> None:
    await update.message.reply_text(
        "📖 *Команды Нюхослава*\n\n"
        "/status — текущая обстановка: ветер и суда в порту\n"
        "/forecast — прогноз риска запаха на 12 часов\n"
        "/smell — сообщить о запахе вручную\n"
        "/history — последние 10 автоматических тревог\n\n"
        "Автоматические тревоги приходят, когда:\n"
        "• танкер стоит в порту достаточно долго\n"
        "• ветер дует в сторону твоего адреса\n"
        "• скорость ветра достаточная",
        parse_mode="Markdown",
    )


async def _handle_smell_command(update: Update, context) -> None:
    vessels = await get_docked_vessels()

    if not vessels:
        await update.message.reply_text(
            "🤷 Сейчас в порту нет зафиксированных судов.\n"
            "Возможно, данные АИС ещё не поступили — попробуй позже."
        )
        return

    lines = ["👃 Ты чувствуешь запах? Выбери судно из тех, что сейчас в порту:\n"]
    buttons = []

    for v in vessels:
        name = v["name"]
        hours = v["docked_hours"]
        lat = v.get("lat")
        lon = v.get("lon")

        if hours < 2:
            marker = "🟢"
        elif hours < 6:
            marker = "🟡"
        elif hours < 24:
            marker = "🟠"
        else:
            marker = "🔴"

        if lat is not None and lon is not None:
            maps_link = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
            loc_part = f"[📍 на карте]({maps_link})"
        else:
            loc_part = "📍 координаты неизвестны"

        lines.append(
            f"{marker} *{name}*\n"
            f"   MMSI: `{v['mmsi']}` · В порту: {hours:.1f}ч\n"
            f"   {loc_part}"
        )

        lat_s = f"{lat:.5f}" if lat is not None else "none"
        lon_s = f"{lon:.5f}" if lon is not None else "none"
        cb = f"smell_vessel:{v['vessel_id']}:{v['visit_id']}:{lat_s}:{lon_s}:{hours:.1f}"
        buttons.append([InlineKeyboardButton(f"🚢 {name}", callback_data=cb)])

    text = "\n\n".join(lines)
    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def _handle_vessel_confirm(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()

    parts = (query.data or "").split(":")
    if len(parts) != 6 or parts[0] != "smell_vessel":
        return

    _, vessel_id_s, visit_id_s, lat_s, lon_s, hours_s = parts

    try:
        vessel_id = int(vessel_id_s)
        visit_id = int(visit_id_s)
        lat = float(lat_s) if lat_s != "none" else None
        lon = float(lon_s) if lon_s != "none" else None
        hours = float(hours_s)
    except ValueError:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vessel_name = None

    async with AsyncSessionLocal() as session:
        visit_result = await session.execute(
            select(VesselPortVisit).where(VesselPortVisit.id == visit_id)
        )
        visit = visit_result.scalar_one_or_none()
        stationary_since = visit.entered_at if visit else None

        vessel_result = await session.execute(
            select(Vessel).where(Vessel.id == vessel_id)
        )
        vessel = vessel_result.scalar_one_or_none()
        vessel_name = vessel.display_name if vessel else f"ID:{vessel_id}"

        session.add(SmellSighting(
            reported_at=now,
            vessel_id=vessel_id,
            visit_id=visit_id,
            vessel_lat=lat,
            vessel_lon=lon,
            stationary_since=stationary_since,
            stationary_hours=hours,
        ))
        await session.commit()

    logger.info(f"Smell sighting recorded: vessel {vessel_name} (id={vessel_id})")

    try:
        await query.edit_message_text(
            f"✅ Запах зафиксирован!\n\n"
            f"Судно: 🚢 {vessel_name}\n"
            f"Записано в {now.strftime('%H:%M')} UTC.\n\n"
            f"Спасибо — это поможет уточнить зону загрузки.",
        )
    except Exception:
        pass


async def _handle_status_command(update: Update, context) -> None:
    wind = await get_latest_wind()
    vessels = await get_docked_vessels()

    now_str = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%H:%M UTC")
    lines = [f"📊 *Обстановка* ({now_str})\n"]

    if wind:
        compass = _degrees_to_compass(wind.direction_deg)
        age_min = int((datetime.now(timezone.utc).replace(tzinfo=None) - wind.recorded_at).total_seconds() / 60)
        lines.append(f"💨 Ветер: {wind.direction_deg:.0f}° ({compass}), {wind.speed_ms:.1f} м/с _{age_min} мин назад_")
    else:
        lines.append("💨 Ветер: данные недоступны")

    if vessels:
        lines.append(f"\n🚢 В порту: {len(vessels)}")
        for v in sorted(vessels, key=lambda x: x["docked_hours"], reverse=True):
            h = v["docked_hours"]
            marker = "🔴" if h >= 24 else "🟠" if h >= 6 else "🟡" if h >= 2 else "🟢"
            tanker = " ⛽" if v["is_tanker"] else ""
            lines.append(f"   {marker} *{v['name']}*{tanker} — {h:.1f}ч")

        if wind:
            risks = [calculate_risk(wind.direction_deg, wind.speed_ms, v["docked_hours"]) for v in vessels]
            best = max(risks, key=lambda r: r.score)
            if best.score > 0:
                lines.append(f"\n⚠️ Риск: *{best.score:.2f}*")
            else:
                reason = "ветер слабый" if best.blocked_by == "wind_too_weak" else "ветер не туда"
                lines.append(f"\n✅ Риск низкий ({reason})")
    else:
        lines.append("\n🚢 Судов в порту нет")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _handle_forecast_command(update: Update, context) -> None:
    forecast = await fetch_hourly_forecast(hours=12)
    vessels = await get_docked_vessels()

    if not forecast:
        await update.message.reply_text("⚠️ Не удалось получить прогноз погоды")
        return

    rows = []
    for entry in forecast:
        hour_str = entry["time"][11:16]  # "HH:MM" from "YYYY-MM-DDTHH:MM"
        spd = entry["speed_ms"]
        dir_deg = entry["direction_deg"]
        hours_from_now = entry["hours_from_now"]
        if vessels:
            score = max(
                calculate_risk(dir_deg, spd, v["docked_hours"] + hours_from_now).score
                for v in vessels
            )
        else:
            score = 0.0
        rows.append((hour_str, dir_deg, spd, score))

    peak_score = max(r[3] for r in rows) if rows else 0.0

    lines = ["🔮 *Прогноз риска на 12ч*\n"]
    for hour_str, dir_deg, spd, score in rows:
        compass = _degrees_to_compass(dir_deg)
        bar = "●" * round(score * 5) + "○" * (5 - round(score * 5))
        peak = " ⬅" if score == peak_score and peak_score > 0 else ""
        lines.append(f"`{hour_str}` {bar} {score:.2f} | {dir_deg:.0f}°{compass} {spd:.1f}м/с{peak}")

    if not vessels:
        lines.append("\n_Судов в порту нет — риск 0_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _handle_history_command(update: Update, context) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SmellAlert)
            .options(selectinload(SmellAlert.vessel), selectinload(SmellAlert.feedback))
            .order_by(desc(SmellAlert.sent_at))
            .limit(10)
        )
        alerts = result.scalars().all()

    if not alerts:
        await update.message.reply_text("📋 Тревог пока не было")
        return

    confirmed_total = 0
    false_total = 0
    lines = ["📋 *Последние тревоги*\n"]

    for i, alert in enumerate(alerts, 1):
        date_str = alert.sent_at.strftime("%d.%m %H:%M")
        vessel_name = alert.vessel.display_name if alert.vessel else "неизвестно"
        fb = max(alert.feedback, key=lambda f: f.reported_at, default=None)
        if fb and fb.feedback_type == "confirmed":
            fb_str = "✅"
            confirmed_total += 1
        elif fb and fb.feedback_type == "false_positive":
            fb_str = "❌"
            false_total += 1
        else:
            fb_str = "—"
        lines.append(f"{i}. {date_str} · *{vessel_name}* · {alert.risk_score:.2f} {fb_str}")

    rated = confirmed_total + false_total
    if rated > 0:
        lines.append(f"\n✅ {confirmed_total} / ❌ {false_total} из {rated} оценено")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def _degrees_to_compass(deg: float) -> str:
    dirs = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
            "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]
    return dirs[round(deg / 22.5) % 16]


async def send_smell_alert(
    vessel_name: str,
    vessel_mmsi: str,
    vessel_id: int | None,
    visit_id: int | None,
    docked_hours: float,
    wind_direction: float,
    wind_speed: float,
    risk_score: float,
) -> int | None:
    if not settings.telegram_bot_token or not settings.telegram_chat_ids:
        logger.warning("Telegram не настроен — уведомление пропущено")
        return None

    compass = _degrees_to_compass(wind_direction)
    text = (
        f"⚠️ Высокий риск запаха (оценка: {risk_score:.2f})\n\n"
        f"🚢 {vessel_name} (MMSI: {vessel_mmsi})\n"
        f"⏱ В порту: {docked_hours:.1f}ч\n"
        f"💨 Ветер: {wind_direction:.0f}° ({compass}), {wind_speed:.1f} м/с\n\n"
        f"Закройте окна!"
    )

    async with AsyncSessionLocal() as session:
        alert = SmellAlert(
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            vessel_id=vessel_id,
            visit_id=visit_id,
            wind_direction=wind_direction,
            wind_speed=wind_speed,
            risk_score=risk_score,
            vessel_docked_hours=docked_hours,
        )
        session.add(alert)
        await session.flush()
        alert_id = alert.id

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Запах есть", callback_data=f"feedback:confirmed:{alert_id}"),
            InlineKeyboardButton("❌ Запаха нет", callback_data=f"feedback:false_positive:{alert_id}"),
        ]])

        first_msg_id = None
        for chat_id in settings.telegram_chat_ids:
            try:
                msg = await get_application().bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                )
                if first_msg_id is None:
                    first_msg_id = msg.message_id
                logger.info(f"Alert {alert_id} sent to {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send Telegram alert to {chat_id}: {e}")

        alert.telegram_message_id = first_msg_id
        await session.commit()

    return alert_id


async def send_all_clear() -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_ids:
        return
    text = "✅ Воздух чистый — можно открыть окна"
    for chat_id in settings.telegram_chat_ids:
        try:
            await get_application().bot.send_message(chat_id=chat_id, text=text)
            logger.info(f"All-clear sent to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send all-clear to {chat_id}: {e}")
