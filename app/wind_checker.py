import logging
from datetime import datetime

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
            recorded_at=datetime.utcnow(),
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
