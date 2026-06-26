# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Odor** is a personal smell-alert system for an apartment near an oil/chemical port. It monitors vessel AIS traffic within a configurable geofence, checks wind direction and speed via Open-Meteo, and sends Telegram alerts when conditions suggest port fumes may reach the user's location. A FastAPI web dashboard shows live tanker status, alert history, and vessel statistics.

## Commands

**Run (Docker — production-like):**
```bash
docker compose up --build   # from repo root; runs migrations automatically
```

**Run tests (no Docker needed — uses SQLite in-memory):**
```bash
cd app && python -m pytest
```

**Run a single test file:**
```bash
cd app && python -m pytest tests/test_smell_estimator.py
```

**Database migrations:**
```bash
# Apply migrations (runs automatically in container via entrypoint.sh)
cd app && alembic upgrade head

# Generate a new migration after changing models.py
cd app && alembic revision --autogenerate -m "describe the change"
```

## Architecture

All application code lives in `app/`. The entry point is `main.py` (FastAPI app with lifespan startup/shutdown).

### Data flow — check cycle

```
scheduler._run_check()  [every CHECK_INTERVAL_MINUTES]
  → vessel_tracker.close_stale_visits()
  → wind_checker.fetch_and_store_wind()    [Open-Meteo API]
  → vessel_tracker.get_docked_vessels()   [from in-memory state]
  → smell_estimator.calculate_risk()      [pure math, no I/O]
  → notifier.send_smell_alert()           [Telegram + DB write]
  → scheduler._schedule_recovery()        [re-checks after ALERT_PAUSE_MINUTES]
```

### Module responsibilities

| File | Role |
|------|------|
| `vessel_tracker.py` | Maintains a persistent WebSocket to AISstream.io. Tracks vessels entering/leaving the geofence. Keeps in-memory dicts (`_active_visits`, `_vessel_last_seen`, `_vessel_positions`) that are restored from DB on startup via `restore_state()`. |
| `wind_checker.py` | Fetches current wind from Open-Meteo API (free, no key). Persists each reading as a `WindReading` row. |
| `smell_estimator.py` | Stateless risk calculation: `calculate_risk(wind_from_deg, wind_speed_ms, docked_hours) → RiskResult`. Score is 0 if wind is too weak or pointing wrong direction; otherwise 0–1 based on angle, speed, and docking time. |
| `scheduler.py` | APScheduler-driven state machine. Two states: *normal* (regular interval checks) and *alerted* (pauses checks, runs recovery job). Module-level `_alerted_at` tracks state. |
| `notifier.py` | Telegram bot initialization and message sending. Handles inline keyboard callbacks: `feedback:confirmed|false_positive:<alert_id>` and `smell_vessel:…` (user-initiated sighting from `/smell` command). `get_application()` returns a singleton `Application`. |
| `main.py` | FastAPI routes + lifespan that starts AISstream task, Telegram polling, and APScheduler. |
| `models.py` | SQLAlchemy ORM: `Vessel`, `VesselPortVisit`, `WindReading`, `SmellAlert`, `AlertFeedback`, `SmellSighting`. |
| `config.py` | Pydantic `Settings` loaded from `.env`. Single `settings` singleton imported everywhere. |
| `database.py` | Async engine + `AsyncSessionLocal` factory + `Base`. |

### Telegram bot commands and callbacks

- `/smell` — user manually reports a smell; bot lists docked vessels with inline buttons
- `feedback:confirmed:<id>` / `feedback:false_positive:<id>` — response to automated alert
- `smell_vessel:<vessel_id>:<visit_id>:<lat>:<lon>:<hours>` — vessel selection from `/smell`

### Geofence and risk thresholds (all configurable via `.env`)

Wind direction uses **meteorological convention** (wind comes *from* that degree). The risk score is zero unless:
1. Wind speed ≥ `WIND_SPEED_MIN_MS`
2. Wind-toward direction is within `WIND_ANGLE_TOLERANCE_DEG` of the port→user bearing

### Adding DB models

1. Add/modify classes in `models.py`
2. Run `alembic revision --autogenerate -m "..."` from `app/`
3. Verify the generated file in `app/alembic/versions/`
4. `alembic upgrade head` applies it (or restart Docker)
