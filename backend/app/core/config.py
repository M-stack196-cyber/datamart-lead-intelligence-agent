import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_env: str
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    """Read process configuration once and normalize comma-separated origins."""
    origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    )
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        cors_origins=origins,
    )
