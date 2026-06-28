import asyncio
import logging
import re
from datetime import date, timedelta

import httpx

from vessel_tracker import register_scraped_vessel

logger = logging.getLogger(__name__)

GORADAR_URL = "https://goradar.ru/port/Novorossiysk"
POLL_INTERVAL_SECONDS = 3600  # 1 hour, as requested

# Maps goradar text vessel types to AIS type codes (80-89 = tanker range).
_TANKER_TYPE_MAP = {
    "tanker": 80,
    "crude oil tanker": 80,
    "oil tanker": 80,
    "oil products tanker": 83,
    "oil/chemical tanker": 82,
    "chemical tanker": 82,
    "chemical oil products tanker": 82,
    "lng tanker": 84,
    "lpg tanker": 85,
    "asphalt/bitumen tanker": 83,
    "bunker vessel": 83,
}

# Vessel list entries: date, name, IMO, MMSI, type text
_ENTRY_RE = re.compile(
    r'<a class="header" href="https://goradar\.ru/vessels_map\.php\?imo=\d+">'
    r'(\d{4}-\d{2}-\d{2})\s+(.*?)</a>\s*'
    r'<div class="description">IMO:\s*(\d+),\s*MMSI:\s*(\d+)\s*\|\s*(.*?)</div>',
    re.DOTALL,
)


def _vessel_type_code(type_text: str) -> int | None:
    normalized = type_text.strip().lower()
    if normalized in _TANKER_TYPE_MAP:
        return _TANKER_TYPE_MAP[normalized]
    # Generic fallback: any type containing "tanker" → AIS tanker range
    if "tanker" in normalized:
        return 80
    return None


async def _fetch_vessels(max_age_days: int = 2) -> list[dict]:
    cutoff = date.today() - timedelta(days=max_age_days)
    results = []

    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get(GORADAR_URL)
        resp.raise_for_status()
        html = resp.text

    for m in _ENTRY_RE.finditer(html):
        date_str, name, imo_str, mmsi_str, type_text = m.groups()

        try:
            seen_date = date.fromisoformat(date_str)
        except ValueError:
            continue

        if seen_date < cutoff:
            continue

        mmsi = mmsi_str.strip()
        if not mmsi or mmsi == "0":
            continue

        results.append({
            "mmsi": mmsi,
            "name": name.strip().strip("'") or None,
            "imo": imo_str.strip() if imo_str.strip() != "0" else None,
            "vessel_type": _vessel_type_code(type_text),
            "seen_date": seen_date,
        })

    seen: set[str] = set()
    deduped = []
    for v in results:
        if v["mmsi"] not in seen:
            seen.add(v["mmsi"])
            deduped.append(v)
    return deduped


async def run_goradar_poller() -> None:
    """Long-running task: poll goradar.ru every hour for recent port vessel arrivals."""
    logger.info("goradar poller started")
    while True:
        try:
            vessels = await _fetch_vessels()
            if not vessels:
                logger.warning("[goradar] No vessels parsed — page structure may have changed")
            else:
                logger.info(f"[goradar] Fetched {len(vessels)} recent vessel(s)")
            for v in vessels:
                await register_scraped_vessel(
                    mmsi=v["mmsi"],
                    name=v["name"],
                    imo=v["imo"],
                    vessel_type=v["vessel_type"],
                    seen_date=v["seen_date"],
                )
        except Exception as e:
            logger.error(f"[goradar] Poll error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
