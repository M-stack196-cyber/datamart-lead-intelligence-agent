from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


CsvTuple = Annotated[tuple[str, ...], BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    """Backend-only configuration loaded without exposing secret values."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: CsvTuple = ("http://localhost:3000",)

    vibe_api_key: str | None = None
    vibe_api_base_url: str = "https://api.explorium.ai"
    vibe_enrichment_enabled: bool = False
    vibe_worker_name: str = "local-vibe-worker"
    vibe_approved_job_limit: int = Field(default=1, ge=1, le=100)
    aws_bearer_token_bedrock: str | None = None
    aws_region: str = "us-east-1"
    bedrock_model_id: str | None = None

    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    database_url: str | None = None

    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"

    @model_validator(mode="after")
    def validate_runtime_environment(self) -> "Settings":
        if self.app_env == "production":
            missing = []
            if not self.supabase_url:
                missing.append("SUPABASE_URL")
            if not self.supabase_anon_key:
                missing.append("SUPABASE_ANON_KEY")
            if not self.supabase_service_role_key:
                missing.append("SUPABASE_SERVICE_ROLE_KEY")
            if not self.database_url:
                missing.append("DATABASE_URL")
            if missing:
                raise ValueError(
                    "Production requires environment variables: " + ", ".join(missing)
                )
        return self

    def integration_status(self) -> dict[str, bool]:
        return {
            "vibe": bool(self.vibe_api_key and self.vibe_enrichment_enabled),
            "bedrock": bool(self.aws_bearer_token_bedrock and self.bedrock_model_id),
            "supabase": bool(
                self.supabase_url
                and self.supabase_anon_key
                and self.supabase_service_role_key
                and self.database_url
            ),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
