import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from models import SmellAlert
from scheduler import _is_in_cooldown


@pytest.mark.asyncio
async def test_cooldown_true_when_recent_alert(db_session):
    alert = SmellAlert(
        sent_at=datetime.utcnow() - timedelta(minutes=30),
        wind_direction=0.0,
        wind_speed=5.0,
        risk_score=0.5,
    )
    db_session.add(alert)
    await db_session.commit()

    with patch("scheduler.AsyncSessionLocal") as mock_sf:
        from unittest.mock import AsyncMock
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("scheduler.settings") as mock_s:
            mock_s.alert_cooldown_hours = 4.0
            result = await _is_in_cooldown()

    assert result is True


@pytest.mark.asyncio
async def test_cooldown_false_when_old_alert(db_session):
    alert = SmellAlert(
        sent_at=datetime.utcnow() - timedelta(hours=6),
        wind_direction=0.0,
        wind_speed=5.0,
        risk_score=0.5,
    )
    db_session.add(alert)
    await db_session.commit()

    with patch("scheduler.AsyncSessionLocal") as mock_sf:
        from unittest.mock import AsyncMock
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("scheduler.settings") as mock_s:
            mock_s.alert_cooldown_hours = 4.0
            result = await _is_in_cooldown()

    assert result is False


@pytest.mark.asyncio
async def test_cooldown_false_when_no_alerts(db_session):
    with patch("scheduler.AsyncSessionLocal") as mock_sf:
        from unittest.mock import AsyncMock
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=db_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("scheduler.settings") as mock_s:
            mock_s.alert_cooldown_hours = 4.0
            result = await _is_in_cooldown()

    assert result is False
