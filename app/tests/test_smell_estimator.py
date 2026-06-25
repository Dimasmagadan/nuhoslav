import pytest
from unittest.mock import patch

from smell_estimator import _angle_diff, _bearing, calculate_risk


# --- _angle_diff ---

def test_angle_diff_simple():
    assert _angle_diff(10, 350) == pytest.approx(20.0)
    assert _angle_diff(350, 10) == pytest.approx(20.0)

def test_angle_diff_opposite():
    assert _angle_diff(0, 180) == pytest.approx(180.0)

def test_angle_diff_same():
    assert _angle_diff(45, 45) == pytest.approx(0.0)


# --- _bearing ---

def test_bearing_due_north():
    # Moving north from equator
    b = _bearing(0.0, 0.0, 1.0, 0.0)
    assert b == pytest.approx(0.0, abs=0.1)

def test_bearing_due_east():
    b = _bearing(0.0, 0.0, 0.0, 1.0)
    assert b == pytest.approx(90.0, abs=0.1)

def test_bearing_due_south():
    b = _bearing(0.0, 0.0, -1.0, 0.0)
    assert b == pytest.approx(180.0, abs=0.1)

def test_bearing_due_west():
    b = _bearing(0.0, 0.0, 0.0, -1.0)
    assert b == pytest.approx(270.0, abs=0.1)


# Settings used throughout (Novorossiysk port defaults from config.py):
# port_center ~(44.74, 37.79), user ~(44.7, 37.8)
# port_to_user bearing ≈ 180° (port is north of user)

def _patch_settings(
    port_to_user_bearing=180.0,
    wind_speed_min_ms=1.5,
    wind_angle_tolerance_deg=45.0,
    user_lat=44.70,
    user_lon=37.80,
    port_lat_min=44.72,
    port_lat_max=44.76,
    port_lon_min=37.76,
    port_lon_max=37.82,
):
    return patch(
        "smell_estimator.settings",
        wind_speed_min_ms=wind_speed_min_ms,
        wind_angle_tolerance_deg=wind_angle_tolerance_deg,
        user_lat=user_lat,
        user_lon=user_lon,
        port_center_lat=(port_lat_min + port_lat_max) / 2,
        port_center_lon=(port_lon_min + port_lon_max) / 2,
    )


def test_risk_wind_toward_user():
    # port is north of user → port_to_user ≈ 180°
    # wind blows south (from_deg=0 → toward=180) → aligned
    with _patch_settings():
        result = calculate_risk(wind_from_deg=0.0, wind_speed_ms=5.0, docked_hours=8.0)
    assert result.score > 0
    assert result.blocked_by is None
    assert result.angle_diff < 45.0


def test_risk_wind_away_from_user():
    # wind blows north (from_deg=180 → toward=0) → wrong direction
    with _patch_settings():
        result = calculate_risk(wind_from_deg=180.0, wind_speed_ms=5.0, docked_hours=8.0)
    assert result.score == 0.0
    assert result.blocked_by == "wrong_direction"


def test_risk_wind_too_weak():
    # Wind speed below minimum — blocked before direction check
    with _patch_settings():
        result = calculate_risk(wind_from_deg=0.0, wind_speed_ms=0.5, docked_hours=8.0)
    assert result.score == 0.0
    assert result.blocked_by == "wind_too_weak"


def test_risk_speed_below_min_overrides_direction():
    # Even if direction is perfect, weak wind returns wind_too_weak not wrong_direction
    with _patch_settings():
        result = calculate_risk(wind_from_deg=0.0, wind_speed_ms=0.0, docked_hours=8.0)
    assert result.blocked_by == "wind_too_weak"


def test_risk_score_increases_with_docked_hours():
    with _patch_settings():
        r1 = calculate_risk(0.0, 5.0, 1.0)
        r2 = calculate_risk(0.0, 5.0, 3.0)
        r3 = calculate_risk(0.0, 5.0, 6.0)
    assert r1.score < r2.score < r3.score


def test_risk_time_factor_caps_at_6h():
    with _patch_settings():
        r_at_6 = calculate_risk(0.0, 5.0, 6.0)
        r_at_12 = calculate_risk(0.0, 5.0, 12.0)
    assert r_at_6.score == pytest.approx(r_at_12.score)


def test_risk_speed_factor_caps_at_8ms():
    with _patch_settings():
        r_at_8 = calculate_risk(0.0, 8.0, 8.0)
        r_at_20 = calculate_risk(0.0, 20.0, 8.0)
    assert r_at_8.score == pytest.approx(r_at_20.score)


def test_risk_at_exact_tolerance_boundary():
    # Port is exactly due north of user (same longitude) → port_to_user = 180°.
    # Tolerance = 45°. Wind from_deg=45 → toward=225; diff=|225-180|=45 exactly.
    # angle_factor = 1 - (45/45) = 0 → score == 0, but not blocked by direction
    # (diff is not *greater than* tolerance, so blocked_by must be None).
    with _patch_settings(
        user_lat=44.70, user_lon=37.80,
        port_lat_min=44.72, port_lat_max=44.72,  # same lat → center exactly 44.72
        port_lon_min=37.80, port_lon_max=37.80,  # same lon as user → due north
        wind_angle_tolerance_deg=45.0,
    ):
        result = calculate_risk(wind_from_deg=45.0, wind_speed_ms=5.0, docked_hours=8.0)
    assert result.blocked_by is None
    assert result.score == pytest.approx(0.0, abs=1e-6)
