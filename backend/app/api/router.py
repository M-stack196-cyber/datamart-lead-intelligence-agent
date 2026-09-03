from fastapi import APIRouter, Depends, HTTPException
from supabase import create_client

from app.api.auth import CurrentUser, require_roles, require_user
from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse
from app.repositories.icp_repository import icp_repository
from app.schemas.icp import IcpDefinition, IcpVersionSummary, LeadProfile, ScoreResult
from app.scoring.icp_engine import IcpScoringEngine
from app.schemas.intake import LeadIntakeBatch, LeadIntakeValidation
from app.services.approval import ApprovalDecision, ApprovalEngine
from app.schemas.outreach import GenerateOutreachRequest, ReviewOutreachRequest
from app.services.outreach import OutreachDraftEngine, validate_outreach_for_approval

router = APIRouter()


def _backend_client(settings: Settings):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Outreach persistence is not configured")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _generate_outreach_draft(
    settings: Settings, actor_id: str, request: GenerateOutreachRequest
) -> dict:
    client = _backend_client(settings)
    lead = client.table("leads").select("*").eq("id", request.lead_id).single().execute().data
    if not lead or lead.get("status") == "disqualified":
        raise ValueError("Lead is not eligible for outreach drafting")
    scores = (
        client.table("lead_scores")
        .select("*")
        .eq("lead_id", request.lead_id)
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not scores or scores[0].get("hard_stops"):
        raise ValueError("An eligible score without hard stops is required")
    evidence = (
        client.table("evidence")
        .select("id,title,source_url,publisher,excerpt,supports_fields")
        .eq("lead_id", request.lead_id)
        .order("captured_at", desc=True)
        .limit(20)
        .execute()
        .data
    )
    draft = OutreachDraftEngine.draft(
        lead,
        evidence or [],
        channel=request.channel,
        persona=scores[0].get("persona"),
    )
    return (
        client.rpc(
            "create_generated_outreach_draft",
            {
                "target_lead_id": request.lead_id,
                "draft_channel": draft["channel"],
                "draft_subject": draft["subject"],
                "draft_body": draft["body"],
                "draft_evidence_ids": draft["evidence_ids"],
                "actor_id": actor_id,
            },
        )
        .execute()
        .data
    )


def _review_outreach_draft(
    settings: Settings,
    actor_id: str,
    draft_id: str,
    request: ReviewOutreachRequest,
) -> dict:
    client = _backend_client(settings)
    draft = (
        client.table("outreach_drafts")
        .select("id,lead_id,body,evidence_ids,status")
        .eq("id", draft_id)
        .single()
        .execute()
        .data
    )
    if not draft:
        raise ValueError("Outreach draft not found")
    evidence_ids = draft.get("evidence_ids") or []
    evidence = []
    if evidence_ids:
        evidence = (
            client.table("evidence")
            .select("id,source_url,title,excerpt")
            .in_("id", evidence_ids)
            .execute()
            .data
            or []
        )
    if request.action == "approved":
        lead = (
            client.table("leads")
            .select("person_name,company_name,title,country,industry")
            .eq("id", draft["lead_id"])
            .single()
            .execute()
            .data
        )
        validate_outreach_for_approval(
            str(draft.get("body") or ""), evidence, lead or {}
        )
    return (
        client.rpc(
            "review_outreach_draft",
            {
                "target_draft_id": draft_id,
                "review_action": request.action,
                "notes": request.review_notes,
                "actor_id": actor_id,
            },
        )
        .execute()
        .data
    )


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


@router.post("/decision/lead", response_model=ApprovalDecision, tags=["decisions"])
async def decide_lead_approval(
    payload: dict,
    _user: CurrentUser = Depends(require_user),
) -> ApprovalDecision:
    """Combine ICP fit and buying intent into a single approval decision for the review queue."""
    lead = payload.get("lead", {}) if isinstance(payload, dict) else {}
    icp_score = int(payload.get("icp_score", 0))
    intent_score = int(payload.get("intent_score", 0))
    evidence_urls = payload.get("evidence_urls", [])
    if not isinstance(evidence_urls, list):
        evidence_urls = []
    return ApprovalEngine().decide(
        lead,
        icp_score=icp_score,
        intent_score=intent_score,
        evidence_urls=evidence_urls,
    )


@router.post("/outreach/drafts/generate", tags=["outreach"])
async def generate_outreach_draft(
    request: GenerateOutreachRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> dict:
    """Generate and persist a reviewable draft from stored facts and evidence."""
    settings = get_settings()
    try:
        return _generate_outreach_draft(settings, user.id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to create outreach draft") from exc


@router.post("/outreach/drafts/{draft_id}/review", tags=["outreach"])
async def review_outreach_draft(
    draft_id: str,
    request: ReviewOutreachRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> dict:
    """Approve or reject an exact stored draft through the server-trusted role gate."""
    settings = get_settings()
    if request.action == "approved" and user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for outreach approval")
    try:
        return _review_outreach_draft(settings, user.id, draft_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to review outreach draft") from exc
