from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import CurrentUser, require_user
from app.core.config import get_settings
from app.schemas.health import HealthResponse
from app.repositories.icp_repository import icp_repository
from app.schemas.icp import IcpDefinition, IcpVersionSummary, LeadProfile, ScoreResult
from app.scoring.icp_engine import IcpScoringEngine
from app.schemas.intake import LeadIntakeBatch, LeadIntakeValidation

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """Report process health and non-secret integration readiness."""
    settings = get_settings()
    integrations = settings.integration_status()
    ready = settings.app_env != "production" or bool(
        integrations["supabase"]
        and integrations["bedrock"]
        and integrations["vibe"]
    )
    return HealthResponse(
        status="healthy",
        environment=settings.app_env,
        ready=ready,
        integrations_configured=integrations,
    )


@router.get("/icp/versions", response_model=list[IcpVersionSummary], tags=["icp"])
async def list_icp_versions(_user: CurrentUser = Depends(require_user)) -> list[IcpVersionSummary]:
    """List immutable ICP versions and their lifecycle status."""
    return icp_repository.list_versions()


@router.get("/icp/versions/active", response_model=IcpDefinition, tags=["icp"])
async def get_active_icp(_user: CurrentUser = Depends(require_user)) -> IcpDefinition:
    """Return the single version used for new lead qualification."""
    try:
        return icp_repository.get_active()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/icp/score", response_model=ScoreResult, tags=["icp"])
async def score_lead(lead: LeadProfile, _user: CurrentUser = Depends(require_user)) -> ScoreResult:
    """Score a lead deterministically and preserve the active ICP version in the result."""
    definition = icp_repository.get_active()
    return IcpScoringEngine(definition).score(lead)


@router.post("/intake/validate", response_model=LeadIntakeValidation, tags=["intake"])
async def validate_lead_intake(
    batch: LeadIntakeBatch, _user: CurrentUser = Depends(require_user)
) -> LeadIntakeValidation:
    """Validate and normalize a lead batch without storing or processing it."""
    return LeadIntakeValidation(valid=True, count=len(batch.rows), rows=batch.rows)
