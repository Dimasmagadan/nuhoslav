import logging
from datetime import datetime

from sqlalchemy import desc, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler

from config import settings
from database import AsyncSessionLocal
from models import AlertFeedback, SmellAlert

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
        _application.add_handler(CallbackQueryHandler(_handle_feedback))
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
            existing.reported_at = datetime.utcnow()
        else:
            session.add(AlertFeedback(
                alert_id=alert_id,
                feedback_type=feedback_type,
                reported_at=datetime.utcnow(),
            ))
        await session.commit()

    emoji = "✅" if feedback_type == "confirmed" else "❌"
    label = "Запах подтверждён" if feedback_type == "confirmed" else "Ложная тревога"
    try:
        await query.edit_message_text(f"{query.message.text}\n\n{emoji} {label}")
    except Exception:
        pass

    logger.info(f"Feedback '{feedback_type}' recorded for alert {alert_id_str}")


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
            sent_at=datetime.utcnow(),
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
