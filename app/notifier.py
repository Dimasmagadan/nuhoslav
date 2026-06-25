import logging
from datetime import datetime

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


async def _handle_feedback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()

    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "feedback":
        return

    _, feedback_type, alert_id_str = parts

    async with AsyncSessionLocal() as session:
        session.add(AlertFeedback(
            alert_id=int(alert_id_str),
            feedback_type=feedback_type,
            reported_at=datetime.utcnow(),
        ))
        await session.commit()

    emoji = "✅" if feedback_type == "confirmed" else "❌"
    label = "smell confirmed" if feedback_type == "confirmed" else "false positive"
    try:
        await query.edit_message_text(
            f"{query.message.text}\n\n{emoji} Marked as {label}",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    logger.info(f"Feedback '{feedback_type}' recorded for alert {alert_id_str}")


def _degrees_to_compass(deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
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
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured — skipping notification")
        return None

    # Save alert first to get an ID for the callback data
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
        await session.commit()
        await session.refresh(alert)
        alert_id = alert.id

    compass = _degrees_to_compass(wind_direction)
    text = (
        f"⚠️ *Smell risk HIGH* (score: {risk_score:.2f})\n\n"
        f"🚢 {vessel_name} (MMSI: {vessel_mmsi})\n"
        f"⏱ In port: {docked_hours:.1f}h\n"
        f"💨 Wind: {wind_direction:.0f}° ({compass}) at {wind_speed:.1f} m/s"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Smell confirmed", callback_data=f"feedback:confirmed:{alert_id}"),
        InlineKeyboardButton("❌ No smell", callback_data=f"feedback:false_positive:{alert_id}"),
    ]])

    try:
        app = get_application()
        msg = await app.bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        async with AsyncSessionLocal() as session:
            saved = await session.get(SmellAlert, alert_id)
            if saved:
                saved.telegram_message_id = msg.message_id
                await session.commit()

        logger.info(f"Alert {alert_id} sent via Telegram")
        return alert_id

    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return None
