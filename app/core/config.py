from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────────────────────
    CEREBRAS_API_KEY: str
    CEREBRAS_MODEL: str = "llama-3.1-8b"

    # ── RapidAPI ─────────────────────────────────────────────────────────────
    RAPIDAPI_KEY: str
    FLIGHT_API_HOST: str = "aerodatabox.p.rapidapi.com"
    HOTEL_API_HOST: str = "booking-com.p.rapidapi.com"

    # Agent URLs are managed by the agent_registry table in the DB.
    # The A2A client wrapper queries the table at runtime.

    # ── Database ─────────────────────────────────────────────────────────────
    DB_PATH: str = str(
        Path(__file__).resolve().parent.parent / "db" / "database.db"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Using lru_cache ensures we only parse the .env file once for the entire
    lifetime of the process — avoids re-reading disk on every import.
    """
    return Settings()


# Convenience singleton — import this everywhere.
settings: Settings = get_settings()
