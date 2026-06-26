# AGENTS.md

AI agent instructions for this repository. See [CLAUDE.md](CLAUDE.md) for the full reference — this file highlights the decisions most likely to cause mistakes.

## Architecture Traps

**In-memory vessel state is authoritative during runtime.** `vessel_tracker.py` keeps `_active_visits`, `_vessel_last_seen`, and `_vessel_positions` as module-level dicts. DB writes happen alongside but the in-memory state drives `get_docked_vessels()`. On startup, `restore_state()` re-hydrates these from DB. Don't bypass this layer by querying `VesselPortVisit` directly when you need live data.

**Scheduler state is module-level.** `_alerted_at` in `scheduler.py` is a plain datetime, not persisted. After a restart, the alerted state is lost — this is intentional (a restart is treated as all-clear).

**Telegram `Application` is a singleton.** Always access it via `notifier.get_application()`. Don't construct a new `Application` anywhere else.

**Wind direction is meteorological (FROM, not TOWARD).** `wind_from_deg` = where wind comes from. `smell_estimator.py` converts to wind-toward internally. Don't flip this convention in tests or new callers.

## Commands

```bash
# Run (Docker)
docker compose up --build

# Tests (no Docker, uses SQLite in-memory)
cd app && python -m pytest

# Single test file
cd app && python -m pytest tests/test_smell_estimator.py

# New migration after editing models.py
cd app && alembic revision --autogenerate -m "description"
```

## Adding Features

- **New alert condition** → modify `smell_estimator.calculate_risk()` or `scheduler._evaluate_risk()`
- **New Telegram command** → add a `CommandHandler` in `notifier.get_application()`
- **New DB table** → add model in `models.py`, then generate migration with alembic
- **New web page** → add route in `main.py`, template in `app/templates/`

## Tests

`tests/conftest.py` provides a `db_session` fixture (async SQLite). Tests that hit external APIs (AISstream, Open-Meteo, Telegram) should mock those calls — don't make real network requests in tests.
