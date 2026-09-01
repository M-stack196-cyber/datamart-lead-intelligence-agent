from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """Report process health and non-secret integration readiness."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        environment=settings.app_env,
        integrations_configured=settings.integration_status(),
    )
