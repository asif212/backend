from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = "sqlite:///./my_time.db"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    RUN_SCHEDULER: bool = False
    MAX_ACCURACY_M: int = 100
    GEOFENCE_RADIUS_M: int = 150
    AUTO_CHECKOUT_GRACE_MINUTES: int = 120


settings = Settings()
