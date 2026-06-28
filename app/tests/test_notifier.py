import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from models import AlertFeedback, SmellAlert, Vessel, VesselPortVisit
from notifier import _degrees_to_compass, _handle_feedback, send_smell_alert


# --- _degrees_to_compass ---

def test_compass_cardinals():
    assert _degrees_to_compass(0) == "С"
    assert _degrees_to_compass(90) == "В"
    assert _degrees_to_compass(180) == "Ю"
    assert _degrees_to_compass(270) == "З"

def test_compass_wraparound():
    assert _degrees_to_compass(360) == "С"

def test_compass_intercardinal():
    assert _degrees_to_compass(22.5) == "ССВ"
    assert _degrees_to_compass(45) == "СВ"


# --- send_smell_alert: no parse_mode regression ---

@pytest.mark.asyncio
async def test_send_alert_no_parse_mode(db_session):
    mock_msg = MagicMock()
    mock_msg.message_id = 42

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)

    mock_app = MagicMock()
    mock_app.bot = mock_bot

    with (
        patch("notifier.get_application", return_value=mock_app),
        patch("notifier.AsyncSessionLocal") as mock_session_factory,
        patch("notifier.settings") as mock_settings,
    ):
        mock_settings.telegram_bot_token = "token"
        mock_settings.telegram_chat_ids = ["123"]
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        await send_smell_alert(
            vessel_name="STAR_OIL*1_TANKER",
            vessel_mmsi="123456789",
            vessel_id=None,
            visit_id=None,
            docked_hours=3.0,
            wind_direction=180.0,
            wind_speed=5.0,
            risk_score=0.75,
        )

    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "parse_mode" not in call_kwargs


# --- _handle_feedback: dedup, validation, int guard ---

def _make_query(data: str, message_text: str = "Alert text"):
    msg = MagicMock()
    msg.text = message_text
    query = AsyncMock()
    query.data = data
    query.message = msg
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


@pytest.mark.asyncio
async def test_feedback_creates_row(db_session):
    # Seed a SmellAlert row
    alert = SmellAlert(
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        wind_direction=0.0,
        wind_speed=5.0,
        risk_score=0.5,
    )
    db_session.add(alert)
    await db_session.flush()
    alert_id = alert.id

    update, _ = _make_query(f"feedback:confirmed:{alert_id}")

    with patch("notifier.AsyncSessionLocal") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        await _handle_feedback(update, None)

    result = await db_session.execute(
        select(AlertFeedback).where(AlertFeedback.alert_id == alert_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].feedback_type == "confirmed"


@pytest.mark.asyncio
async def test_feedback_dedup_same_button_twice(db_session):
    alert = SmellAlert(
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        wind_direction=0.0,
        wind_speed=5.0,
        risk_score=0.5,
    )
    db_session.add(alert)
    await db_session.flush()
    alert_id = alert.id

    with patch("notifier.AsyncSessionLocal") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        update, _ = _make_query(f"feedback:confirmed:{alert_id}")
        await _handle_feedback(update, None)
        update2, _ = _make_query(f"feedback:confirmed:{alert_id}")
        await _handle_feedback(update2, None)

    result = await db_session.execute(
        select(AlertFeedback).where(AlertFeedback.alert_id == alert_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_feedback_dedup_both_buttons(db_session):
    alert = SmellAlert(
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        wind_direction=0.0,
        wind_speed=5.0,
        risk_score=0.5,
    )
    db_session.add(alert)
    await db_session.flush()
    alert_id = alert.id

    with patch("notifier.AsyncSessionLocal") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        update1, _ = _make_query(f"feedback:confirmed:{alert_id}")
        await _handle_feedback(update1, None)
        update2, _ = _make_query(f"feedback:false_positive:{alert_id}")
        await _handle_feedback(update2, None)

    result = await db_session.execute(
        select(AlertFeedback).where(AlertFeedback.alert_id == alert_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].feedback_type == "false_positive"


@pytest.mark.asyncio
async def test_feedback_invalid_type_no_row(db_session):
    alert = SmellAlert(
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        wind_direction=0.0,
        wind_speed=5.0,
        risk_score=0.5,
    )
    db_session.add(alert)
    await db_session.flush()
    alert_id = alert.id

    update, _ = _make_query(f"feedback:hacked:{alert_id}")
    with patch("notifier.AsyncSessionLocal") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        await _handle_feedback(update, None)

    result = await db_session.execute(
        select(AlertFeedback).where(AlertFeedback.alert_id == alert_id)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_feedback_bad_alert_id_no_exception(db_session):
    update, _ = _make_query("feedback:confirmed:not_a_number")
    with patch("notifier.AsyncSessionLocal") as mock_sf:
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        # Should not raise
        await _handle_feedback(update, None)
