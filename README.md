# Нюхослав

A personal smell-alert system for an apartment near an oil/chemical port. Monitors vessel AIS traffic in a configurable geofence, checks wind conditions, and sends Telegram alerts when port fumes are likely to reach your location.

## How It Works

1. **AISstream.io WebSocket** — tracks ships entering and leaving the port geofence in real time
2. **Open-Meteo API** — fetches current wind direction and speed at your coordinates (free, no key needed)
3. **Risk estimation** — score 0–1 based on wind pointing from port toward you, wind speed, and how long the vessel has been docked
4. **Telegram alert** — sent when risk > 0, with inline buttons to confirm or dismiss ("smell is real" / "false alarm")
5. **Recovery check** — after an alert, re-checks on a short interval and sends an all-clear when risk drops

Users can also trigger manual sightings via the `/smell` Telegram command — the bot lists currently docked vessels and records which one you're blaming.

## Quick Start

### Prerequisites

- Docker + Docker Compose
- [AISstream.io](https://aisstream.io) free account (for vessel tracking)
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Telegram chat ID (get it from [@userinfobot](https://t.me/userinfobot))

### Setup

```bash
cp .env.example .env
# Edit .env — set coordinates, Telegram credentials, AISstream key
docker compose up --build
```

The app runs at `http://localhost:8000`. Migrations run automatically on startup.

### Configuration (`.env`)

| Variable | Description |
|----------|-------------|
| `USER_LAT` / `USER_LON` | Your apartment coordinates |
| `PORT_LAT_MIN/MAX` / `PORT_LON_MIN/MAX` | Port geofence bounding box |
| `VESSEL_DOCKED_HOURS` | Min hours docked before a vessel qualifies (default: 2) |
| `WIND_ANGLE_TOLERANCE_DEG` | ±degrees from port→you bearing (default: 45) |
| `WIND_SPEED_MIN_MS` | Min wind speed to carry smell (default: 1.5 m/s) |
| `CHECK_INTERVAL_MINUTES` | How often the check cycle runs (default: 30) |
| `ALERT_PAUSE_MINUTES` | Pause between alert and first recovery check (default: 10) |
| `ALERT_TIMEOUT_HOURS` | Max time in alerted state before silent reset (default: 1) |
| `AISSTREAM_API_KEY` | AISstream.io API key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | One or more chat IDs, comma-separated |

## Web Dashboard

| Route | Description |
|-------|-------------|
| `/` | Live status: active tankers, current wind, recent alerts |
| `/vessels` | Vessel history with confirmed-smell statistics |
| `/history` | Last 100 alerts with feedback |
| `/health` | JSON health check |
| `/trigger-check` | Manually run a check cycle (POST) |

## Stack

- **FastAPI** + **Jinja2** — web app and dashboard
- **python-telegram-bot** — Telegram integration
- **SQLAlchemy** (async) + **PostgreSQL** — persistence
- **Alembic** — database migrations
- **APScheduler** — periodic check cycles
- **websockets** — AISstream.io connection
- **httpx** — Open-Meteo API calls

## Development

Tests use SQLite in-memory and need no running services:

```bash
cd app && python -m pytest
```

Generate a DB migration after editing `models.py`:

```bash
cd app && alembic revision --autogenerate -m "describe change"
```
