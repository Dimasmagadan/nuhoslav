import math
from dataclasses import dataclass

from config import settings


@dataclass
class RiskResult:
    score: float          # 0.0–1.0
    angle_diff: float     # degrees between wind direction and port→user bearing
    wind_toward_deg: float
    port_to_user_bearing: float
    blocked_by: str | None  # 'wind_too_weak' | 'wrong_direction' | None


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing from point 1 to point 2, degrees clockwise from north."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angle_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return diff if diff <= 180 else 360 - diff


def evaluate_weather_risk(wind_from_deg: float, wind_speed_ms: float) -> RiskResult:
    """Weather-only risk gate — no vessel data needed. Returns blocked_by=None if conditions could carry smell."""
    port_to_user = _bearing(
        settings.port_center_lat, settings.port_center_lon,
        settings.user_lat, settings.user_lon,
    )
    wind_toward = (wind_from_deg + 180) % 360
    diff = _angle_diff(wind_toward, port_to_user)

    if wind_speed_ms < settings.wind_speed_min_ms:
        return RiskResult(0.0, diff, wind_toward, port_to_user, "wind_too_weak")

    if diff > settings.wind_angle_tolerance_deg:
        return RiskResult(0.0, diff, wind_toward, port_to_user, "wrong_direction")

    angle_factor = 1.0 - (diff / settings.wind_angle_tolerance_deg)
    speed_factor = min(wind_speed_ms / 8.0, 1.0)
    return RiskResult(angle_factor * speed_factor, diff, wind_toward, port_to_user, None)


def calculate_risk(wind_from_deg: float, wind_speed_ms: float, docked_hours: float) -> RiskResult:
    """Returns a risk score 0–1. Delegates weather geometry to evaluate_weather_risk."""
    weather = evaluate_weather_risk(wind_from_deg, wind_speed_ms)
    if weather.blocked_by:
        return weather
    time_factor = min(docked_hours / 6.0, 1.0)  # 6+ hours = full score
    return RiskResult(
        weather.score * time_factor,
        weather.angle_diff,
        weather.wind_toward_deg,
        weather.port_to_user_bearing,
        None,
    )
