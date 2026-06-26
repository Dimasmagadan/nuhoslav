import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import scheduler as sched_module


@pytest.mark.asyncio
async def test_run_check_skipped_when_recently_alerted():
    """Regular cycle is skipped while alerted state is within timeout."""
    sched_module._alerted_at = datetime.utcnow() - timedelta(minutes=5)
    try:
        with (
            patch("scheduler.close_stale_visits", new_callable=AsyncMock),
            patch("scheduler.fetch_and_store_wind", new_callable=AsyncMock) as mock_wind,
            patch("scheduler.settings") as mock_s,
        ):
            mock_s.alert_timeout_hours = 1.0
            await sched_module._run_check()
        mock_wind.assert_not_called()
    finally:
        sched_module._alerted_at = None


@pytest.mark.asyncio
async def test_run_check_resets_expired_alerted_state():
    """Alerted state is cleared once timeout has elapsed."""
    sched_module._alerted_at = datetime.utcnow() - timedelta(hours=2)
    try:
        with (
            patch("scheduler.close_stale_visits", new_callable=AsyncMock),
            patch("scheduler.fetch_and_store_wind", new_callable=AsyncMock, return_value=None),
            patch("scheduler.settings") as mock_s,
        ):
            mock_s.alert_timeout_hours = 1.0
            await sched_module._run_check()
        assert sched_module._alerted_at is None
    finally:
        sched_module._alerted_at = None


@pytest.mark.asyncio
async def test_recovery_sends_all_clear_when_risk_zero():
    """Recovery check sends all-clear message when risk drops to zero."""
    sched_module._alerted_at = datetime.utcnow() - timedelta(minutes=15)
    try:
        wind_mock = AsyncMock()
        wind_mock.direction_deg = 180.0
        wind_mock.speed_ms = 5.0

        with (
            patch("scheduler.fetch_and_store_wind", new_callable=AsyncMock, return_value=wind_mock),
            patch("scheduler.get_docked_vessels", new_callable=AsyncMock, return_value=[]),
            patch("scheduler.send_all_clear", new_callable=AsyncMock) as mock_clear,
            patch("scheduler.settings") as mock_s,
        ):
            mock_s.alert_timeout_hours = 1.0
            mock_s.vessel_docked_hours = 2.0
            await sched_module._recovery_check()

        mock_clear.assert_called_once()
        assert sched_module._alerted_at is None
    finally:
        sched_module._alerted_at = None
