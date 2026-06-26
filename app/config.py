from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://odor:odor@db:5432/odor"
    database_url_sync: str = "postgresql+psycopg2://odor:odor@db:5432/odor"

    user_lat: float = 44.7
    user_lon: float = 37.8

    port_lat_min: float = 44.72
    port_lat_max: float = 44.76
    port_lon_min: float = 37.76
    port_lon_max: float = 37.82

    vessel_docked_hours: float = 2.0
    wind_angle_tolerance_deg: float = 45.0
    wind_speed_min_ms: float = 1.5
    alert_pause_minutes: int = 10       # pause after alert before resuming checks
    alert_timeout_hours: float = 1.0    # max time in alerted state before reset
    check_interval_minutes: int = 30

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""          # comma-separated for multiple recipients

    @property
    def telegram_chat_ids(self) -> list[str]:
        return [cid.strip() for cid in self.telegram_chat_id.split(",") if cid.strip()]

    aisstream_api_key: str = ""

    @property
    def port_center_lat(self) -> float:
        return (self.port_lat_min + self.port_lat_max) / 2

    @property
    def port_center_lon(self) -> float:
        return (self.port_lon_min + self.port_lon_max) / 2


settings = Settings()
