import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models import SmellAlert
from notifier import send_smell_alert
from smell_estimator import calculate_risk
from vessel_tracker import close_stale_visits, get_active_tankers
from wind_checker import fetch_and_store_wind

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_check_lock = asyncio.Lock()


async def check_cycle() -> None:
    if _check_lock.locked():
        logger.info("check_cycle already running — skipping concurrent invocation")
        return
    async with _check_lock:
        await _run_check()


async def _run_check() -> None:
    logger.info("=== Smell check cycle started ===")

    await close_stale_visits()

    wind = await fetch_and_store_wind()
    if wind is None:
        logger.warning("No wind data — skipping risk evaluation")
        return

    tankers = await get_active_tankers()
    # Include vessels with unknown type (type=None) since we might not have static data yet
    qualifying = [
        t for t in tankers
        if (t["is_tanker"] or t["vessel_type"] is None)
        and t["docked_hours"] >= settings.vessel_docked_hours
    ]

    if not qualifying:
        logger.info(f"No qualifying tankers (total in port: {len(tankers)})")
        return

    worst = max(qualifying, key=lambda t: t["docked_hours"])
    risk = calculate_risk(wind.direction_deg, wind.speed_ms, worst["docked_hours"])

    logger.info(
        f"Risk: {risk.score:.2f} | blocked_by: {risk.blocked_by} | "
        f"vessel: {worst['name']} ({worst['docked_hours']:.1f}h) | "
        f"wind: {wind.direction_deg:.0f}° {wind.speed_ms:.1f}m/s"
    )

    if risk.score <= 0.0:
        return

    if await _is_in_cooldown():
        logger.info("Alert suppressed — cooldown active")
        return

    await send_smell_alert(
        vessel_name=worst["name"],
        vessel_mmsi=worst["mmsi"],
        vessel_id=worst["vessel_id"],
        visit_id=worst["visit_id"],
        docked_hours=worst["docked_hours"],
        wind_direction=wind.direction_deg,
        wind_speed=wind.speed_ms,
        risk_score=risk.score,
    )


async def _is_in_cooldown() -> bool:
    cutoff = datetime.utcnow() - timedelta(hours=settings.alert_cooldown_hours)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SmellAlert).where(SmellAlert.sent_at >= cutoff).limit(1)
        )
        return result.scalar_one_or_none() is not None


def start_scheduler() -> None:
    scheduler.add_job(
        check_cycle,
        "interval",
        minutes=settings.check_interval_minutes,
        id="smell_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — interval: {settings.check_interval_minutes} min")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
