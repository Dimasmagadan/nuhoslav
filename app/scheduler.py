import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from notifier import send_all_clear, send_smell_alert, send_weather_warning_no_vessels
from smell_estimator import calculate_risk, evaluate_weather_risk
from vessel_tracker import close_stale_visits, get_ais_data_age_minutes, get_docked_vessels
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


async def _get_qualifying_tankers() -> list[dict]:
    """Return docked tankers that have been in port long enough to matter."""
    vessels = await get_docked_vessels()
    return [
        t for t in vessels
        if (t["is_tanker"] or t["vessel_type"] is None)
        and t["docked_hours"] >= settings.vessel_docked_hours
    ]


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

    # Gate 1: weather conditions — skip vessel check entirely if wind is harmless
    wind = await fetch_and_store_wind()
    if wind is None:
        logger.warning("No wind data — skipping risk evaluation")
        return

    weather_risk = evaluate_weather_risk(wind.direction_deg, wind.speed_ms)
    if weather_risk.blocked_by:
        logger.info(f"Weather not risky ({weather_risk.blocked_by}) — skipping vessel check")
        return

    logger.info(
        f"Weather gate passed | wind: {wind.direction_deg:.0f}° {wind.speed_ms:.1f}m/s "
        f"| angle_diff: {weather_risk.angle_diff:.1f}°"
    )

    # Gate 2: AIS data freshness — warn if we can't check for vessels
    ais_age = get_ais_data_age_minutes()
    if ais_age is None or ais_age > settings.ais_stale_threshold_minutes:
        logger.warning(f"AIS data unavailable (age={ais_age} min) — sending soft weather warning")
        alert_id = await send_weather_warning_no_vessels(wind.direction_deg, wind.speed_ms, weather_risk)
        if alert_id is not None:
            _alerted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            _schedule_recovery()
        return

    # Gate 3: qualifying tankers present
    qualifying = await _get_qualifying_tankers()
    if not qualifying:
        logger.info("No qualifying tankers")
        return

    worst = max(qualifying, key=lambda t: t["docked_hours"])
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
    wind = await fetch_and_store_wind()
    if wind is None:
        logger.warning("Recovery check: no wind data — rescheduling")
        _schedule_recovery()
        return

    weather_risk = evaluate_weather_risk(wind.direction_deg, wind.speed_ms)
    if weather_risk.blocked_by:
        logger.info(f"Recovery check: weather cleared ({weather_risk.blocked_by}) — sending all-clear")
        await send_all_clear()
        _alerted_at = None
        return

    risk_score = 0.0
    qualifying = await _get_qualifying_tankers()
    if qualifying:
        worst = max(qualifying, key=lambda t: t["docked_hours"])
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
