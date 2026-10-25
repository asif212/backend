from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = "sqlite:///./my_time.db"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    RUN_SCHEDULER: bool = False
    WEBSITE_DATA_DIR: str = "./website_data"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/website/reviews/google/callback"
    MAX_ACCURACY_M: int = 100
    GEOFENCE_RADIUS_M: int = 150
    AUTO_CHECKOUT_GRACE_MINUTES: int = 120


settings = Settings()
