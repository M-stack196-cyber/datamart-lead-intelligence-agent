from secrets import compare_digest
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from supabase import create_client

from app.api.auth import CurrentUser, require_roles, require_user
from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse
from app.repositories.icp_repository import icp_repository
from app.schemas.icp import IcpDefinition, IcpVersionSummary, LeadProfile, ScoreResult
from app.scoring.icp_engine import IcpScoringEngine
from app.schemas.intake import LeadIntakeBatch, LeadIntakeValidation
from app.services.approval import ApprovalDecision, ApprovalEngine
from app.schemas.outreach import (
    CrmSyncRequest,
    DraftStatusReviewRequest,
    GenerateOutreachRequest,
    IngestInboundReplyRequest,
    ManualSendRequest,
    NextFollowupDraftRequest,
    PauseSequenceRequest,
    PrimaryDraftRequest,
    ReplyWaitRequest,
    ReviewOutreachRequest,
    RunDueFollowupsRequest,
    SaveOutreachDraftRequest,
    SendEmailRequest,
)
from app.integrations.gmail import GmailClient, GmailDeliveryError
from app.integrations.outbound import InboundReplyRequest
from app.lead_sources import ApolloLeadSourceProvider, ProviderAuthError
from app.services.email_delivery import EmailDeliveryService
from app.services.lead_source_ingestion import prepare_and_score_leads
from app.services.lead_source_persistence import persist_scored_leads, service_role_client
from app.services.outreach import OutreachDraftEngine, validate_outreach_for_approval
from app.services.outreach_generation import (
    generate_outreach_message,
    get_outreach_state,
    list_outreach_leads,
    regenerate_outreach,
    save_outreach_draft,
)
from app.services.outreach_delivery import (
    approve_outreach_message,
    send_outreach_message,
)
from app.services.sequence_execution import (
    get_sequence_state,
    pause_sequence,
    resume_sequence,
    run_due_followups,
    schedule_next_followup,
)
from app.services.reply_ingestion import (
    ingest_inbound_reply,
    list_inbound_replies,
)
from app.services.crm_handoff import (
    get_crm_sync_state,
    push_lead_to_crm,
)
from app.services.outreach_analytics import (
    get_lead_outreach_analytics,
    get_lead_outreach_timeline,
)
from app.services.review_workspace import (
    review_outreach_draft_status,
    review_workspace_leads,
)
from app.services.next_followup_drafts import (
    create_next_followup_draft,
    mark_draft_manually_sent,
    stop_draft_followup,
    update_draft_reply_wait,
)
from app.services.primary_outreach_drafts import create_primary_outreach_draft
from app.services.lead_backup_export import build_lead_backup_csv, build_lead_backup_preview

from app.services.vibe_discovery_cycle import approved_daily_limit, run_vibe_discovery_cycle

router = APIRouter()


def _now_sql() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_cron_secret(settings: Settings, authorization: str | None) -> None:
    if not settings.cron_secret:
        raise HTTPException(
            status_code=503,
            detail="Cron authentication is not configured",
        )

    expected = f"Bearer {settings.cron_secret}"

    if authorization is None or not compare_digest(authorization, expected):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


def _backend_client(settings: Settings):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Outreach persistence is not configured")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _generate_outreach_message(
    settings: Settings,
    actor_id: str,
    actor_role: str,
    lead_id: str,
    *,
    channel: str = "email",
) -> dict:
    return generate_outreach_message(settings, actor_id, actor_role, lead_id, channel=channel)


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
    if (
        not scores
        or scores[0].get("hard_stops")
        or scores[0].get("disposition") not in {"Strong Fit", "Good Fit"}
    ):
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
        validate_outreach_for_approval(str(draft.get("body") or ""), evidence, lead or {})
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


def _send_approved_email(settings: Settings, actor_id: str, draft_id: str) -> dict:
    if not settings.integration_status()["gmail"]:
        raise RuntimeError("Gmail sending is disabled until all Gmail settings are configured")
    client = _backend_client(settings)
    attempt = (
        client.rpc(
            "begin_email_delivery_attempt",
            {
                "target_draft_id": draft_id,
                "actor_id": actor_id,
                "sender_email": settings.gmail_sender_email,
            },
        )
        .execute()
        .data
    )
    if not isinstance(attempt, dict) or not attempt.get("attempt_id"):
        raise RuntimeError("Email delivery attempt could not be created")

    transport = GmailClient(
        settings.gmail_client_id or "",
        settings.gmail_client_secret or "",
        settings.gmail_refresh_token or "",
    )
    try:
        delivery = EmailDeliveryService(transport).send(
            sender=str(attempt["sender"]),
            recipient=str(attempt["recipient"]),
            subject=str(attempt["subject"]),
            body=str(attempt["body"]),
        )
    except Exception as exc:
        client.rpc(
            "finish_email_delivery_attempt",
            {
                "target_attempt_id": attempt["attempt_id"],
                "succeeded": False,
                "provider_message_id": None,
                "safe_error": "Gmail provider request failed",
                "actor_id": actor_id,
            },
        ).execute()
        if isinstance(exc, ValueError):
            raise
        raise GmailDeliveryError("Gmail provider request failed") from exc

    result = (
        client.rpc(
            "finish_email_delivery_attempt",
            {
                "target_attempt_id": attempt["attempt_id"],
                "succeeded": True,
                "provider_message_id": delivery.message_id,
                "safe_error": None,
                "actor_id": actor_id,
            },
        )
        .execute()
        .data
    )
    try:
        draft_rows = (
            client.table("outreach_drafts")
            .select("sent_at")
            .eq("id", draft_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except AttributeError:
        draft_rows = []
    existing_sent_at = draft_rows[0].get("sent_at") if draft_rows and isinstance(draft_rows[0], dict) else None
    try:
        client.table("outreach_drafts").update(
            {
                "status": "system_sent",
                "reviewed_by": actor_id,
                "reviewed_at": _now_sql(),
                "sent_at": existing_sent_at or _now_sql(),
            }
        ).eq("id", draft_id).execute()
    except AttributeError:
        pass
    return {
        "status": "sent",
        "attempt_id": attempt["attempt_id"],
        "provider_message_id": delivery.message_id,
        "delivery": result,
    }


def _review_workspace_payload(
    settings: Settings,
    *,
    source: str,
    status: str,
    limit: int,
    include_drafts: bool,
) -> dict:
    client = _backend_client(settings)
    result = review_workspace_leads(
        client,
        source=source,
        status=status,
        limit=limit,
        include_drafts=include_drafts,
    )
    return {
        "source": result.source,
        "status": result.status,
        "limit": result.limit,
        "leads": result.leads,
    }


def _review_draft_status(
    settings: Settings,
    actor_id: str,
    draft_id: str,
    request: DraftStatusReviewRequest,
) -> dict:
    client = _backend_client(settings)
    return review_outreach_draft_status(
        client,
        draft_id=draft_id,
        action=request.action,
        review_notes=request.review_notes,
        actor_id=actor_id,
    )


def _mark_manual_send(
    settings: Settings,
    actor_id: str,
    draft_id: str,
    request: ManualSendRequest,
) -> dict:
    return mark_draft_manually_sent(
        _backend_client(settings),
        draft_id=draft_id,
        actor_id=actor_id,
        notes=request.review_notes,
        reply_wait_days=request.reply_wait_days,
        next_followup_decision_at=request.next_followup_decision_at,
    )


def _update_reply_wait(
    settings: Settings,
    actor_id: str,
    draft_id: str,
    request: ReplyWaitRequest,
) -> dict:
    return update_draft_reply_wait(
        _backend_client(settings),
        draft_id=draft_id,
        actor_id=actor_id,
        reply_wait_days=request.reply_wait_days,
        next_followup_decision_at=request.next_followup_decision_at,
    )


def _stop_followup(
    settings: Settings,
    actor_id: str,
    draft_id: str,
) -> dict:
    return stop_draft_followup(
        _backend_client(settings),
        draft_id=draft_id,
        actor_id=actor_id,
    )


def _create_next_followup(
    settings: Settings,
    actor_id: str,
    lead_id: str,
    request: NextFollowupDraftRequest,
) -> dict:
    result = create_next_followup_draft(
        _backend_client(settings),
        lead_id=lead_id,
        actor_id=actor_id,
        channel=request.channel,
        source=request.source,
    )
    return {
        "lead_id": result.lead_id,
        "source": result.source,
        "results": {
            channel: {
                "channel": item.channel,
                "created": item.created,
                "reason": item.reason,
                "sequence_step": item.sequence_step,
                "draft": item.draft,
                "message": item.message,
            }
            for channel, item in result.results.items()
        },
    }


def _create_primary_outreach(
    settings: Settings,
    actor_id: str,
    lead_id: str,
    request: PrimaryDraftRequest,
) -> dict:
    result = create_primary_outreach_draft(
        _backend_client(settings),
        lead_id=lead_id,
        actor_id=actor_id,
        channel=request.channel,
        source=request.source,
    )
    return {
        "lead_id": result.lead_id,
        "source": result.source,
        "results": {
            channel: {
                "channel": item.channel,
                "created": item.created,
                "reason": item.reason,
                "sequence_step": item.sequence_step,
                "draft": item.draft,
            }
            for channel, item in result.results.items()
        },
    }


def _lead_backup_export(
    settings: Settings,
    *,
    source: str | None,
    status: str | None,
    limit: int,
) -> tuple[str, str, str]:
    export = build_lead_backup_csv(
        _backend_client(settings),
        source=source,
        status=status,
        limit=limit,
    )
    return export.content, export.filename, export.content_type


def _lead_backup_preview(
    settings: Settings,
    *,
    source: str | None,
    status: str | None,
    limit: int,
) -> dict:
    return build_lead_backup_preview(
        _backend_client(settings),
        source=source,
        status=status,
        limit=limit,
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


@router.get("/leads/review-workspace", tags=["leads"])
async def lead_review_workspace(
    source: str = Query(default="apollo_csv", min_length=1, max_length=100),
    status: str = Query(default="review", min_length=1, max_length=50),
    limit: int = Query(default=50, ge=1, le=200),
    include_drafts: bool = Query(default=True),
    _user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Return review leads with latest score and grouped draft sequence state."""
    try:
        return _review_workspace_payload(
            get_settings(),
            source=source,
            status=status,
            limit=limit,
            include_drafts=include_drafts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to load review workspace") from exc


@router.get("/leads/backup-export", tags=["leads"])
async def lead_backup_export(
    source: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=1000, ge=1, le=5000),
    format: str = Query(default="csv", pattern="^csv$"),
    _user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> Response:
    """Download a CSV backup of lead, scoring, draft, send, and reply history."""
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only csv export is supported")
    try:
        content, filename, content_type = _lead_backup_export(
            get_settings(),
            source=source,
            status=status,
            limit=limit,
        )
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to generate lead backup export") from exc


@router.get("/leads/backup-preview", tags=["leads"])
async def lead_backup_preview(
    source: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=1000, ge=1, le=5000),
    _user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> dict:
    """Return a reviewable JSON preview of the lead backup without full draft bodies."""
    try:
        return _lead_backup_preview(
            get_settings(),
            source=source,
            status=status,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to generate lead backup preview") from exc


@router.get("/outreach", tags=["outreach"])
async def list_outreach(
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> list[dict]:
    """List sales-approved leads that the current user may prepare for outreach."""
    try:
        return list_outreach_leads(get_settings(), user.id, user.role)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to list outreach leads") from exc


@router.get("/outreach/{lead_id}", tags=["outreach"])
async def get_outreach_for_lead(
    lead_id: str,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Return the current outreach record, latest draft, and evidence state for a sales-eligible lead."""
    settings = get_settings()
    try:
        return get_outreach_state(settings, user.id, user.role, lead_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to fetch outreach state") from exc


@router.post("/outreach/generate", tags=["outreach"])
async def generate_outreach(
    request: GenerateOutreachRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Generate an evidence-grounded outbound message only for sales-approved, non-suppressed leads."""
    settings = get_settings()
    try:
        return _generate_outreach_message(
            settings, user.id, user.role, request.lead_id, channel=request.channel
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to generate outreach message") from exc


@router.post("/outreach/{lead_id}/save", tags=["outreach"])
async def save_outreach(
    lead_id: str,
    request: SaveOutreachDraftRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Persist edits to an unsent outreach draft with an event log."""
    settings = get_settings()
    try:
        return save_outreach_draft(
            settings,
            user.id,
            user.role,
            lead_id,
            subject=request.subject or "",
            body=request.body,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to save outreach draft") from exc


@router.post("/outreach/{lead_id}/regenerate", tags=["outreach"])
async def regenerate_outreach_route(
    lead_id: str,
    _request: dict | None = None,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Regenerate a draft without mutating a sent message."""
    settings = get_settings()
    try:
        return regenerate_outreach(settings, user.id, user.role, lead_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to regenerate outreach") from exc




@router.post("/outreach/{lead_id}/approve", tags=["outreach"])
async def approve_outreach(
    lead_id: str,
    user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Explicitly approve an unsent Phase B outreach draft before delivery."""
    try:
        return approve_outreach_message(
            get_settings(),
            user.id,
            user.role,
            lead_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to approve outreach message",
        ) from exc


@router.post("/outreach/{lead_id}/send", tags=["outreach"])
async def send_outreach(
    lead_id: str,
    _request: SendEmailRequest,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> dict:
    """Send only an explicitly approved Phase B outreach message."""
    try:
        settings = get_settings()

        result = send_outreach_message(
            settings,
            user.id,
            user.role,
            lead_id,
        )

        if result.get("status") == "sent":
            sequence = schedule_next_followup(
                settings,
                user.id,
                user.role,
                lead_id,
            )
            result["sequence"] = sequence

        return result
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to send outreach message",
        ) from exc



@router.post("/outreach/{lead_id}/replies", tags=["outreach"])
async def ingest_outreach_reply(
    lead_id: str,
    request: IngestInboundReplyRequest,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> dict:
    """Ingest and classify an inbound reply for an outreach sequence."""
    try:
        inbound = InboundReplyRequest(
            provider_name=request.provider_name,
            lead_id=lead_id,
            lead_outreach_id=request.lead_outreach_id,
            thread_id=request.thread_id,
            provider_message_id=request.provider_message_id,
            from_email=request.from_email,
            to_email=request.to_email,
            subject=request.subject,
            body=request.body,
            received_at=request.received_at,
            metadata=request.metadata,
        )

        return ingest_inbound_reply(
            get_settings(),
            user.id,
            user.role,
            inbound,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to ingest inbound reply",
        ) from exc


@router.get("/outreach/{lead_id}/replies", tags=["outreach"])
async def outreach_replies(
    lead_id: str,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> list[dict]:
    """Return inbound replies visible to the current user."""
    try:
        return list_inbound_replies(
            get_settings(),
            user.id,
            user.role,
            lead_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to load inbound replies",
        ) from exc


@router.get("/outreach/{lead_id}/timeline", tags=["outreach"])
async def outreach_timeline(
    lead_id: str,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> list[dict]:
    """Return chronological outreach activity for a lead."""
    try:
        return get_lead_outreach_timeline(
            get_settings(),
            user.id,
            user.role,
            lead_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to load outreach timeline",
        ) from exc


@router.get("/outreach/{lead_id}/analytics", tags=["outreach"])
async def outreach_analytics(
    lead_id: str,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> dict:
    """Return outreach analytics summary for a lead."""
    try:
        return get_lead_outreach_analytics(
            get_settings(),
            user.id,
            user.role,
            lead_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to load outreach analytics",
        ) from exc


@router.post("/outreach/{lead_id}/crm-sync", tags=["outreach"])
async def sync_outreach_lead_to_crm(
    lead_id: str,
    request: CrmSyncRequest,
    user: CurrentUser = Depends(
        require_roles("admin", "manager")
    ),
) -> dict:
    """Push a lead to the configured CRM provider."""
    try:
        return push_lead_to_crm(
            get_settings(),
            user.id,
            user.role,
            lead_id,
            request.provider_key,
            request.mapping,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to sync lead to CRM",
        ) from exc


@router.get("/outreach/{lead_id}/crm-sync", tags=["outreach"])
async def outreach_crm_sync_state(
    lead_id: str,
    provider_key: str | None = None,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> list[dict]:
    """Return CRM synchronization state for a lead."""
    try:
        return get_crm_sync_state(
            get_settings(),
            user.id,
            user.role,
            lead_id,
            provider_key=provider_key,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to load CRM sync state",
        ) from exc


@router.get("/outreach/{lead_id}/sequence", tags=["outreach"])
async def outreach_sequence_state(
    lead_id: str,
    user: CurrentUser = Depends(
        require_roles("admin", "manager", "sales")
    ),
) -> dict:
    """Return the current sequence state and follow-up history for a lead."""
    try:
        return get_sequence_state(
            get_settings(),
            user.id,
            user.role,
            lead_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to load outreach sequence",
        ) from exc


@router.post("/outreach/{lead_id}/sequence/pause", tags=["outreach"])
async def pause_outreach_sequence(
    lead_id: str,
    request: PauseSequenceRequest,
    user: CurrentUser = Depends(
        require_roles("admin", "manager")
    ),
) -> dict:
    """Pause future automated follow-ups for a lead."""
    try:
        return pause_sequence(
            get_settings(),
            user.id,
            user.role,
            lead_id,
            reason=request.reason,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to pause outreach sequence",
        ) from exc


@router.post("/outreach/{lead_id}/sequence/resume", tags=["outreach"])
async def resume_outreach_sequence(
    lead_id: str,
    user: CurrentUser = Depends(
        require_roles("admin", "manager")
    ),
) -> dict:
    """Resume a previously paused outreach sequence."""
    try:
        return resume_sequence(
            get_settings(),
            user.id,
            user.role,
            lead_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to resume outreach sequence",
        ) from exc


@router.post("/outreach/sequences/run-due", tags=["outreach"])
async def execute_due_outreach_sequences(
    request: RunDueFollowupsRequest,
    user: CurrentUser = Depends(
        require_roles("admin", "manager")
    ),
) -> dict:
    """Process currently due automated email follow-ups."""
    try:
        return run_due_followups(
            get_settings(),
            user.id,
            user.role,
            limit=request.limit,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to process due follow-ups",
        ) from exc


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
    if request.action in {"approve", "approved"} and user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for outreach approval")
    if request.action == "needs_edit":
        try:
            return review_outreach_draft_status(
                _backend_client(settings),
                draft_id=draft_id,
                action="needs_edit",
                review_notes=request.review_notes,
                actor_id=user.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Unable to review outreach draft") from exc
    if request.action in {"approve", "reject"}:
        request = ReviewOutreachRequest(
            action={"approve": "approved", "reject": "rejected"}[request.action],
            review_notes=request.review_notes,
        )
    try:
        return _review_outreach_draft(settings, user.id, draft_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to review outreach draft") from exc


@router.patch("/outreach-drafts/{draft_id}/review", tags=["outreach"])
async def review_outreach_draft_status_route(
    draft_id: str,
    request: DraftStatusReviewRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> dict:
    """Update a draft review status without sending or invoking delivery providers."""
    if request.action == "approve" and user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for outreach approval")
    try:
        return _review_draft_status(get_settings(), user.id, draft_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to update draft review status") from exc


@router.patch("/outreach-drafts/{draft_id}/manual-send", tags=["outreach"])
async def mark_outreach_draft_manually_sent(
    draft_id: str,
    request: ManualSendRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Record that a team member sent a draft manually without provider delivery calls."""
    try:
        return _mark_manual_send(get_settings(), user.id, draft_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to mark draft as manually sent") from exc


@router.patch("/outreach-drafts/{draft_id}/reply-wait", tags=["outreach"])
async def update_outreach_draft_reply_wait(
    draft_id: str,
    request: ReplyWaitRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Set or extend the team-selected reply wait before follow-up draft decisions."""
    try:
        return _update_reply_wait(get_settings(), user.id, draft_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to update reply wait") from exc


@router.patch("/outreach-drafts/{draft_id}/stop-followup", tags=["outreach"])
async def stop_outreach_draft_followup(
    draft_id: str,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Record a team decision to stop future follow-up after a sent draft."""
    try:
        return _stop_followup(get_settings(), user.id, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to stop follow-up") from exc


@router.post("/leads/{lead_id}/outreach/next-followup-draft", tags=["outreach"])
async def create_next_followup_draft_route(
    lead_id: str,
    request: NextFollowupDraftRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Create only the next allowed follow-up draft, never a sent message."""
    try:
        return _create_next_followup(get_settings(), user.id, lead_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to create next follow-up draft") from exc


@router.post("/leads/{lead_id}/outreach/primary-draft", tags=["outreach"])
async def create_primary_outreach_draft_route(
    lead_id: str,
    request: PrimaryDraftRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Create only the requested primary draft channel by explicit team action."""
    try:
        return _create_primary_outreach(get_settings(), user.id, lead_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to create primary outreach draft") from exc


@router.post("/outreach/drafts/{draft_id}/send-email", tags=["outreach"])
async def send_approved_email(
    draft_id: str,
    _request: SendEmailRequest,
    user: CurrentUser = Depends(require_roles("admin", "manager", "sales")),
) -> dict:
    """Send only after the caller posts an explicit literal confirmation."""
    try:
        return _send_approved_email(get_settings(), user.id, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GmailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to send approved email") from exc


@router.get("/internal/vibe/discovery-cycle")
async def run_internal_vibe_discovery_cycle(
    authorization: str | None = Header(default=None),
    limit: int | None = Query(default=None, ge=1),
):
    settings = get_settings()
    _require_cron_secret(settings, authorization)

    if (
        not settings.supabase_url
        or not settings.supabase_service_role_key
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Supabase service-role "
                "configuration is required"
            ),
        )

    if not settings.vibe_api_key:
        raise HTTPException(
            status_code=503,
            detail="Vibe API configuration is required",
        )

    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )

    try:
        requested_limit = approved_daily_limit(
            limit,
            settings.daily_vibe_lead_limit,
            allow_over_cap=settings.vibe_allow_over_daily_cap,
        )
        result = run_vibe_discovery_cycle(
            client,
            size=requested_limit,
            page_size=min(requested_limit, 100),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to complete the Vibe discovery cycle",
        ) from exc

    return {
        "status": "completed_with_errors" if result.errors else "completed",
        "requested_limit": result.requested_limit,
        "fetched_count": result.fetched_count,
        "stored_count": result.stored_count,
        "duplicate_count": result.duplicate_count,
        "qualified_count": result.qualified_count,
        "review_count": result.review_count,
        "rejected_count": result.rejected_count,
        "evidence_count": result.evidence_count,
        "draft_count": result.draft_count,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get("/internal/lead-sources/apollo/discovery-cycle")
async def run_internal_apollo_discovery_cycle(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    persist: bool = Query(default=False),
):
    settings = get_settings()
    _require_cron_secret(settings, authorization)

    try:
        leads = ApolloLeadSourceProvider(settings=settings).fetch_leads(limit)
        result = prepare_and_score_leads(leads)
    except ProviderAuthError as exc:
        status_code = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to complete the Apollo discovery cycle",
        ) from exc

    return {
        "status": "completed_with_errors" if result.errors else "completed",
        "requested_limit": limit,
        "fetched_count": len(leads),
        "prepared_count": result.prepared_count,
        "duplicate_count": result.duplicate_count,
        "qualified_count": result.qualified_count,
        "review_count": result.review_count,
        "rejected_count": result.rejected_count,
        "errors": result.errors,
        "warnings": result.warnings,
        **(
            {
                "persistence": _persist_apollo_discovery_result(settings, result),
            }
            if persist
            else {"persistence": None}
        ),
    }


def _persist_apollo_discovery_result(settings: Settings, result) -> dict:
    persisted = persist_scored_leads(
        service_role_client(settings),
        result,
        file_name="apollo-api-discovery-cycle",
    )
    return {
        "inserted_count": persisted.inserted_count,
        "updated_count": persisted.updated_count,
        "duplicate_count": persisted.duplicate_count,
        "lead_score_count": persisted.lead_score_count,
        "errors": persisted.errors,
        "warnings": persisted.warnings,
    }
