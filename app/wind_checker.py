import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, desc

from config import settings
from database import AsyncSessionLocal
from models import WindReading

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_and_store_wind() -> WindReading | None:
    params = {
        "latitude": settings.user_lat,
        "longitude": settings.user_lon,
        "current": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current", {})
        direction = current.get("wind_direction_10m")
        speed = current.get("wind_speed_10m")

        if direction is None or speed is None:
            logger.error(f"Unexpected Open-Meteo response: {data}")
            return None

        reading = WindReading(
            recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
            direction_deg=float(direction),
            speed_ms=float(speed),
        )
        async with AsyncSessionLocal() as session:
            session.add(reading)
            await session.commit()
            await session.refresh(reading)

        logger.info(f"Wind: {direction:.0f}° at {speed:.1f} m/s")
        return reading

    except Exception as e:
        logger.error(f"Failed to fetch wind data: {e}")
        return None


async def get_latest_wind() -> WindReading | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(WindReading).order_by(desc(WindReading.recorded_at)).limit(1)
        )
        return result.scalar_one_or_none()


async def fetch_hourly_forecast(hours: int = 12) -> list[dict]:
    """Fetch hourly wind forecast for the next N hours. Returns list of {time, speed_ms, direction_deg, hours_from_now}."""
    params = {
        "latitude": settings.user_lat,
        "longitude": settings.user_lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
        "forecast_days": 2,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        speeds = hourly.get("wind_speed_10m", [])
        directions = hourly.get("wind_direction_10m", [])

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = []
        for t, s, d in zip(times, speeds, directions):
            if s is None or d is None:
                continue
            forecast_time = datetime.strptime(t, "%Y-%m-%dT%H:%M")
            hours_from_now = (forecast_time - now).total_seconds() / 3600
            if hours_from_now < -0.5:
                continue
            result.append({"time": t, "speed_ms": s, "direction_deg": d, "hours_from_now": max(hours_from_now, 0.0)})
            if len(result) >= hours:
                break
        return result

    except Exception as e:
        logger.error(f"Failed to fetch wind forecast: {e}")
        return []
