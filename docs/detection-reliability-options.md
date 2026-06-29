# Detection Reliability Options — No Free AIS Provider

## Context

The system relies on AISstream.io WebSocket for vessel presence. Without reliable positions, the core detection loop (`vessel_tracker` → geofence check → `docked_vessels`) breaks down. The system already has a weather-first fallback (soft warning without AIS), but that produces false positives. The goal is better vessel-presence signal without hardware or paid AIS.

Key insight from code: `calculate_risk()` only needs `docked_hours`, `wind_from_deg`, `wind_speed_ms`. AIS is purely a "is anyone home?" oracle. Any alternative that answers that question is a valid substitute.

---

## Options (ranked by effort × impact)

### 1. Air Quality APIs — direct smell proxy (no vessel data needed)
**Effort: low | Impact: high if a station exists near the port**

Instead of inferring smell risk from vessel presence, query a real air quality sensor near the port. If PM2.5 / VOC / H₂S is elevated AND wind is toward you → high confidence.

- **WAQI (World Air Quality Index)** — `api.waqi.info` — free, 1000 req/day, covers Russia
- **OpenAQ** — `api.openaq.org` — free, global, historical + real-time
- Integration point: `scheduler._run_check()` — add `air_quality_checker.fetch()` alongside `wind_checker`, gate the alert on `aqi_elevated AND weather_risk`
- **Risk**: Magadan may have no nearby monitoring stations. Check `api.waqi.info/search/?token=demo&keyword=Magadan` first.

### 2. Alternative AIS providers — drop-in for AISstream

| Provider | Free tier | Notes |
|---|---|---|
| **MarineTraffic** | Very limited (1 call/min, small vessel count) | Has REST API, not WebSocket |
| **VesselFinder** | Free tier with delays | REST, not real-time |
| **Datalastic** | ~$10/mo for basic | REST, good coverage |
| **AISHub** | Free *if you contribute data* | Chicken-and-egg without receiver |
| **aisstream.io** | Check if free tier still works | Already integrated |

Implementation: make `vessel_tracker` backend-agnostic (extract `AISProvider` interface), add a polling REST adapter for MarineTraffic or VesselFinder as fallback when WebSocket drops.

### 3. Port schedule scraping — deterministic vessel presence
**Effort: medium | Impact: medium (lags reality, no type info)**

Many Russian ports publish vessel arrival/departure schedules on their official websites or via SeaRates/Ports.com. If the specific port has a public schedule:
- Scrape or poll the schedule page on a cron
- Create synthetic "expected docking" events with estimated duration
- Lower confidence alerts (flag as "schedule-based, not AIS-confirmed")

Needs: manual identification of the port's public data URL.

### 4. RTL-SDR receiver — permanent fix, ~$25
**Effort: medium hardware setup | Impact: highest**

An RTL-SDR USB dongle ($15-30) plugged into any always-on machine (old laptop, Pi, NAS) running `AIS-catcher` or `rtl_ais` decodes raw AIS broadcasts from vessels in range (typically 20-50 km on water).

- Eliminates all third-party provider dependency
- Feeds local UDP/TCP stream → replace AISstream WebSocket with local socket in `vessel_tracker.py`
- For Magadan: vessels in the port would be well within range
- Software: `AIS-catcher` (Docker image available), outputs NMEA or JSON

### 5. Sensor fusion — combine existing signals better
**Effort: low | Impact: medium (no new data, smarter use of existing)**

Current fallback already sends soft warnings when AIS is stale. Improvements:
- Add confidence tiers to alerts: `AIS-confirmed` / `weather-only` / `schedule-inferred` / `AQ-corroborated`
- Tune `AIS_DATA_MAX_AGE_HOURS` down: send weather-only alerts sooner when AIS drops
- Track "last confirmed vessel" timestamp in DB — if a vessel was confirmed docked 6h ago and wind is right, still include it as "possibly still present"

This is a pure code change in `scheduler.py` and `notifier.py`.

---

## Recommended Priority

1. **Check WAQI for nearby stations** (5 minutes, free) — if a station exists near the port, add air quality as a corroborating signal. Biggest bang for zero cost.
2. **Sensor fusion / lingering vessel heuristic** (hours of code) — extend last-confirmed-vessel window before declaring AIS unavailable.
3. **RTL-SDR** — when hardware budget allows; solves the problem permanently.

---

## Verification

- WAQI check: `curl "https://api.waqi.info/search/?token=demo&keyword=Magadan"` → look for stations within 10 km of the port
- For any new data source: add integration test in `tests/` using the in-memory SQLite setup already in place
- Manual end-to-end: trigger `scheduler._run_check()` via `/status` Telegram command and observe alert behavior with and without AIS data
