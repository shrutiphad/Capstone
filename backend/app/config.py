from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/hotel_db"

    GROQ_API_KEY: str = ""  # ← changed

    CONFIDENCE_THRESHOLD: float = 0.6
    CANCEL_CONFIDENCE_THRESHOLD: float = 0.75
    OTA_URL: str = "http://localhost:9000"
    OTA_MAX_RETRIES: int = 5

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()