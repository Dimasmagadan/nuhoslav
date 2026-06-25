import asyncio
import json
import logging
from datetime import datetime

import websockets
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models import Vessel, VesselPortVisit

logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# In-memory state (survives between WebSocket reconnects)
_vessel_last_seen: dict[str, datetime] = {}
_active_visits: dict[str, int] = {}  # mmsi -> visit.id


async def _upsert_vessel(session, mmsi: str, **kwargs) -> Vessel:
    result = await session.execute(select(Vessel).where(Vessel.mmsi == mmsi))
    vessel = result.scalar_one_or_none()
    now = datetime.utcnow()
    if vessel is None:
        vessel = Vessel(mmsi=mmsi, first_seen=now, last_seen=now, **kwargs)
        session.add(vessel)
    else:
        vessel.last_seen = now
        for k, v in kwargs.items():
            if v is not None:
                setattr(vessel, k, v)
    await session.flush()
    return vessel


async def _handle_position_report(msg: dict) -> None:
    meta = msg.get("MetaData", {})
    mmsi = str(meta.get("MMSI", "")).strip()
    if not mmsi:
        return

    lat = meta.get("latitude") or meta.get("Latitude")
    lon = meta.get("longitude") or meta.get("Longitude")
    if lat is None or lon is None:
        return

    in_port = (
        settings.port_lat_min <= lat <= settings.port_lat_max
        and settings.port_lon_min <= lon <= settings.port_lon_max
    )
    if not in_port:
        return

    _vessel_last_seen[mmsi] = datetime.utcnow()
    name = meta.get("ShipName", "").strip() or None

    async with AsyncSessionLocal() as session:
        vessel = await _upsert_vessel(session, mmsi, name=name)

        if mmsi not in _active_visits:
            visit = VesselPortVisit(vessel_id=vessel.id, entered_at=datetime.utcnow())
            session.add(visit)
            await session.flush()
            _active_visits[mmsi] = visit.id
            logger.info(f"Vessel {vessel.display_name} entered port")

        await session.commit()


async def _handle_static_data(msg: dict) -> None:
    meta = msg.get("MetaData", {})
    mmsi = str(meta.get("MMSI", "")).strip()
    if not mmsi:
        return

    static = msg.get("Message", {}).get("ShipStaticData", {})
    async with AsyncSessionLocal() as session:
        await _upsert_vessel(
            session,
            mmsi,
            vessel_type=static.get("ShipType"),
            imo=str(static.get("Imo", "")).strip() or None,
            name=static.get("Name", "").strip() or None,
            callsign=static.get("CallSign", "").strip() or None,
        )
        await session.commit()


async def close_stale_visits() -> None:
    """Mark vessels as departed if not seen for >90 minutes."""
    now = datetime.utcnow()
    stale = [
        mmsi for mmsi, last in _vessel_last_seen.items()
        if (now - last).total_seconds() > 5400
    ]
    if not stale:
        return

    async with AsyncSessionLocal() as session:
        for mmsi in stale:
            visit_id = _active_visits.pop(mmsi, None)
            _vessel_last_seen.pop(mmsi, None)
            if visit_id:
                result = await session.execute(
                    select(VesselPortVisit).where(VesselPortVisit.id == visit_id)
                )
                visit = result.scalar_one_or_none()
                if visit and visit.left_at is None:
                    visit.left_at = now
                    logger.info(f"Vessel MMSI:{mmsi} departed port")
        await session.commit()


async def get_active_tankers() -> list[dict]:
    """Return currently docked vessels with docking duration."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(VesselPortVisit, Vessel)
            .join(Vessel, VesselPortVisit.vessel_id == Vessel.id)
            .where(VesselPortVisit.left_at.is_(None))
        )
        rows = result.all()

    return [
        {
            "mmsi": vessel.mmsi,
            "name": vessel.display_name,
            "vessel_type": vessel.vessel_type,
            "is_tanker": vessel.is_tanker,
            "docked_hours": visit.duration_hours,
            "visit_id": visit.id,
            "vessel_id": vessel.id,
        }
        for visit, vessel in rows
    ]


async def run_aisstream() -> None:
    """Long-running task: maintain WebSocket connection to AISstream.io."""
    if not settings.aisstream_api_key:
        logger.warning("AISSTREAM_API_KEY not set — vessel tracking disabled")
        return

    subscribe_msg = {
        "APIKey": settings.aisstream_api_key,
        "BoundingBoxes": [[
            [settings.port_lat_min, settings.port_lon_min],
            [settings.port_lat_max, settings.port_lon_max],
        ]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }

    while True:
        try:
            logger.info("Connecting to AISstream.io...")
            async with websockets.connect(AISSTREAM_URL, ping_interval=30) as ws:
                await ws.send(json.dumps(subscribe_msg))
                logger.info("AISstream.io connected")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        msg_type = msg.get("MessageType")
                        if msg_type == "PositionReport":
                            await _handle_position_report(msg)
                        elif msg_type == "ShipStaticData":
                            await _handle_static_data(msg)
                    except Exception as e:
                        logger.error(f"Error processing AIS message: {e}")
        except Exception as e:
            logger.error(f"AISstream.io error: {e} — reconnecting in 60s")
            await asyncio.sleep(60)
