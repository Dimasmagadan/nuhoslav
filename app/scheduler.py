import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from notifier import send_all_clear, send_smell_alert
from smell_estimator import calculate_risk
from vessel_tracker import close_stale_visits, get_docked_vessels
from wind_checker import fetch_and_store_wind

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_check_lock = asyncio.Lock()
_alerted_at: datetime | None = None


async def check_cycle() -> None:
    if _check_lock.locked():
        logger.info("check_cycle already running — skipping concurrent invocation")
        return
    async with _check_lock:
        await _run_check()


async def _evaluate_risk():
    """Returns (wind, worst_vessel_or_none)."""
    wind = await fetch_and_store_wind()
    if wind is None:
        return None, None
    tankers = await get_docked_vessels()
    qualifying = [
        t for t in tankers
        if (t["is_tanker"] or t["vessel_type"] is None)
        and t["docked_hours"] >= settings.vessel_docked_hours
    ]
    if not qualifying:
        return wind, None
    return wind, max(qualifying, key=lambda t: t["docked_hours"])


def _schedule_recovery() -> None:
    scheduler.add_job(
        _recovery_check,
        "date",
        run_date=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=settings.alert_pause_minutes),
        id="smell_recovery",
        replace_existing=True,
    )
    logger.info(f"Recovery check scheduled in {settings.alert_pause_minutes} min")


async def _run_check() -> None:
    global _alerted_at

    logger.info("=== Smell check cycle started ===")
    await close_stale_visits()

    if _alerted_at is not None:
        elapsed_h = (datetime.now(timezone.utc).replace(tzinfo=None) - _alerted_at).total_seconds() / 3600
        if elapsed_h < settings.alert_timeout_hours:
            logger.info("Smell check skipped — alerted state active (recovery job handles it)")
            return
        _alerted_at = None  # timeout expired, reset silently

    wind, worst = await _evaluate_risk()
    if wind is None:
        logger.warning("No wind data — skipping risk evaluation")
        return
    if worst is None:
        logger.info("No qualifying tankers")
        return

    risk = calculate_risk(wind.direction_deg, wind.speed_ms, worst["docked_hours"])
    logger.info(
        f"Risk: {risk.score:.2f} | blocked_by: {risk.blocked_by} | "
        f"vessel: {worst['name']} ({worst['docked_hours']:.1f}h) | "
        f"wind: {wind.direction_deg:.0f}° {wind.speed_ms:.1f}m/s"
    )

    if risk.score < settings.risk_threshold:
        return

    alert_id = await send_smell_alert(
        vessel_name=worst["name"],
        vessel_mmsi=worst["mmsi"],
        vessel_id=worst["vessel_id"],
        visit_id=worst["visit_id"],
        docked_hours=worst["docked_hours"],
        wind_direction=wind.direction_deg,
        wind_speed=wind.speed_ms,
        risk_score=risk.score,
    )
    if alert_id is not None:
        _alerted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        _schedule_recovery()


async def _recovery_check() -> None:
    global _alerted_at
    if _alerted_at is None:
        return

    elapsed_h = (datetime.now(timezone.utc).replace(tzinfo=None) - _alerted_at).total_seconds() / 3600
    if elapsed_h >= settings.alert_timeout_hours:
        logger.info("Recovery check: timeout expired — resetting to normal")
        _alerted_at = None
        return

    logger.info("=== Recovery check started ===")
    wind, worst = await _evaluate_risk()

    if wind is None:
        logger.warning("Recovery check: no wind data — rescheduling")
        _schedule_recovery()
        return

    risk_score = 0.0
    if worst is not None:
        risk = calculate_risk(wind.direction_deg, wind.speed_ms, worst["docked_hours"])
        risk_score = risk.score
        logger.info(f"Recovery: risk={risk_score:.2f} | elapsed={elapsed_h:.2f}h")

    if risk_score < settings.risk_threshold:
        logger.info("Recovery check: risk cleared — sending all-clear")
        await send_all_clear()
        _alerted_at = None
    else:
        logger.info("Recovery check: risk still high — rescheduling")
        _schedule_recovery()


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
