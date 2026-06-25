import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import engine, get_db
from models import AlertFeedback, SmellAlert, Vessel, VesselPortVisit
from notifier import get_application
from scheduler import check_cycle, start_scheduler, stop_scheduler
from vessel_tracker import get_docked_vessels, restore_state, run_aisstream
from wind_checker import get_latest_wind

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

_aisstream_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _aisstream_task

    await restore_state()

    if settings.aisstream_api_key:
        _aisstream_task = asyncio.create_task(run_aisstream())

    if settings.telegram_bot_token:
        tg = get_application()
        await tg.initialize()
        await tg.start()
        await tg.updater.start_polling(drop_pending_updates=True)

    start_scheduler()
    yield

    stop_scheduler()
    if settings.telegram_bot_token:
        tg = get_application()
        await tg.updater.stop()
        await tg.stop()
        await tg.shutdown()
    if _aisstream_task:
        _aisstream_task.cancel()
        await asyncio.gather(_aisstream_task, return_exceptions=True)
    await engine.dispose()


app = FastAPI(title="Odor", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    active_tankers = await get_docked_vessels()
    wind = await get_latest_wind()

    result = await db.execute(
        select(SmellAlert)
        .options(selectinload(SmellAlert.vessel), selectinload(SmellAlert.feedback))
        .order_by(desc(SmellAlert.sent_at))
        .limit(5)
    )
    recent_alerts = result.scalars().all()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_tankers": active_tankers,
        "wind": wind,
        "recent_alerts": recent_alerts,
        "settings": settings,
    })


@app.get("/vessels", response_class=HTMLResponse)
async def vessels_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Subqueries: distinct alert IDs that have each feedback type
    confirmed_sq = (
        select(AlertFeedback.alert_id)
        .where(AlertFeedback.feedback_type == "confirmed")
        .distinct()
        .subquery()
    )
    false_pos_sq = (
        select(AlertFeedback.alert_id)
        .where(AlertFeedback.feedback_type == "false_positive")
        .distinct()
        .subquery()
    )

    stmt = (
        select(
            Vessel,
            func.count(SmellAlert.id).label("total_alerts"),
            func.count(confirmed_sq.c.alert_id).label("confirmed"),
            func.count(false_pos_sq.c.alert_id).label("false_positives"),
        )
        .outerjoin(SmellAlert, SmellAlert.vessel_id == Vessel.id)
        .outerjoin(confirmed_sq, confirmed_sq.c.alert_id == SmellAlert.id)
        .outerjoin(false_pos_sq, false_pos_sq.c.alert_id == SmellAlert.id)
        .group_by(Vessel.id)
        .order_by(desc(Vessel.last_seen))
    )

    rows = (await db.execute(stmt)).all()
    stats = [
        {
            "vessel": vessel,
            "total_alerts": total,
            "confirmed": confirmed,
            "false_positives": false_pos,
            "stink_rate": confirmed / total if total > 0 else None,
        }
        for vessel, total, confirmed, false_pos in rows
    ]
    stats.sort(key=lambda x: (x["confirmed"], x["stink_rate"] or 0), reverse=True)

    return templates.TemplateResponse("vessels.html", {"request": request, "vessels": stats})


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SmellAlert)
        .options(selectinload(SmellAlert.vessel), selectinload(SmellAlert.feedback))
        .order_by(desc(SmellAlert.sent_at))
        .limit(100)
    )
    alerts = result.scalars().all()
    return templates.TemplateResponse("history.html", {"request": request, "alerts": alerts})


@app.get("/health")
async def health():
    tankers = await get_docked_vessels()
    wind = await get_latest_wind()
    return {
        "status": "ok",
        "active_tankers": len(tankers),
        "wind": {
            "direction_deg": wind.direction_deg,
            "speed_ms": wind.speed_ms,
            "recorded_at": wind.recorded_at.isoformat(),
        } if wind else None,
    }


@app.post("/trigger-check")
async def trigger_check():
    """Manually run a check cycle (useful for testing)."""
    await check_cycle()
    return RedirectResponse(url="/", status_code=303)
