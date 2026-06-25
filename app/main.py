import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import Base, engine, get_db
from models import SmellAlert, Vessel, VesselPortVisit
from notifier import get_application
from scheduler import check_cycle, start_scheduler, stop_scheduler
from vessel_tracker import get_active_tankers, run_aisstream
from wind_checker import get_latest_wind

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

_aisstream_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _aisstream_task

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    await engine.dispose()


app = FastAPI(title="Odor", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    active_tankers = await get_active_tankers()
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
    result = await db.execute(
        select(Vessel)
        .options(selectinload(Vessel.alerts).selectinload(SmellAlert.feedback))
        .order_by(desc(Vessel.last_seen))
    )
    vessel_list = result.scalars().all()

    stats = []
    for v in vessel_list:
        total = len(v.alerts)
        confirmed = sum(
            1 for a in v.alerts
            if any(f.feedback_type == "confirmed" for f in a.feedback)
        )
        false_pos = sum(
            1 for a in v.alerts
            if any(f.feedback_type == "false_positive" for f in a.feedback)
        )
        stats.append({
            "vessel": v,
            "total_alerts": total,
            "confirmed": confirmed,
            "false_positives": false_pos,
            "stink_rate": confirmed / total if total > 0 else None,
        })

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
    tankers = await get_active_tankers()
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
