from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from supabase import create_client

from app.core.config import Settings
from app.integrations.bedrock.client import BedrockClient
from app.schemas.outbound import SuppressionEntry, SuppressionKind
from app.services.outbound import build_idempotency_key, is_suppressed
from app.services.outreach import OutreachDraftEngine, validate_outreach_for_approval


_FALLBACK_LEADS: dict[str, dict[str, Any]] = {
    "lead-01": {"id": "lead-01", "status": "review", "email": "lead-01@datamart.test", "person_name": "Avery Chen", "company_name": "Northstar Labs", "title": "VP of Revenue", "country": "United States", "industry": "software", "linkedin_url": "https://www.linkedin.com/in/averychen", "company_url": "https://northstarlabs.example", "sales_approved_at": "2026-09-01T00:00:00Z", "assigned_to": "user-1"},
    "lead-02": {"id": "lead-02", "status": "review", "email": "lead-02@datamart.test", "person_name": "Jordan Lee", "company_name": "Harbor Health", "title": "Head of Growth", "country": "United States", "industry": "healthcare", "sales_approved_at": None, "assigned_to": "user-1"},
    "lead-03": {"id": "lead-03", "status": "disqualified", "email": "lead-03@datamart.test", "person_name": "Morgan Patel", "company_name": "Summit Cloud", "title": "Operations Lead", "country": "United States", "industry": "saas", "sales_approved_at": "2026-09-01T00:00:00Z", "assigned_to": "user-1"},
    "lead-04": {"id": "lead-04", "status": "review", "email": "suppressed@datamart.test", "person_name": "Taylor Brooks", "company_name": "Blue Peak", "title": "Director of Marketing", "country": "United States", "industry": "software", "sales_approved_at": "2026-09-01T00:00:00Z", "assigned_to": "user-1"},
    "lead-05": {"id": "lead-05", "status": "review", "email": "lead-05@datamart.test", "person_name": "Robin Flores", "company_name": "Atlas Finance", "title": "CRO", "country": "United States", "industry": "fintech", "sales_approved_at": "2026-09-01T00:00:00Z", "assigned_to": "user-1"},
}
_FALLBACK_EVIDENCE: dict[str, list[dict[str, Any]]] = {
    "lead-01": [{"id": "src-1", "title": "Northstar Labs product expansion", "source_url": "https://example.com/northstar-expansion", "publisher": "Example News", "excerpt": "Northstar Labs expanded its analytics platform across enterprise revenue teams.", "supports_fields": ["company_activity"]}],
    "lead-05": [{"id": "src-5", "title": "Atlas Finance operating update", "source_url": "https://example.com/atlas-finance-update", "publisher": "Fintech Brief", "excerpt": "Atlas Finance reported continued expansion across enterprise banking products.", "supports_fields": ["company_activity"]}],
}
_FALLBACK_SCORES: dict[str, dict[str, Any]] = {
    "lead-01": {"score": 82, "disposition": "Strong Fit", "evaluations": [{"criterion": "Decision-maker seniority", "outcome": "matched"}], "intent_score": 71, "intent_level": "high", "intent_reasons": ["Recent enterprise product expansion"], "scored_at": "2026-09-01T00:00:00Z"},
    "lead-05": {"score": 76, "disposition": "Good Fit", "evaluations": [{"criterion": "Target industry", "outcome": "matched"}], "intent_score": 58, "intent_level": "medium", "intent_reasons": ["Enterprise product expansion"], "scored_at": "2026-09-01T00:00:00Z"},
}
_FALLBACK_STATE: dict[str, dict[str, Any]] = {}


def reset_fallback_outreach_state() -> None:
    """Reset the local-only store used by tests and unconfigured development."""
    _FALLBACK_STATE.clear()


def _uses_fallback(settings: Settings) -> bool:
    return not (settings.supabase_url and settings.supabase_service_role_key)


def _client(settings: Settings):
    if _uses_fallback(settings):
        raise RuntimeError("Outreach persistence is not configured")
    return create_client(settings.supabase_url or "", settings.supabase_service_role_key or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lead(settings: Settings, lead_id: str) -> dict[str, Any]:
    if _uses_fallback(settings):
        lead = _FALLBACK_LEADS.get(lead_id)
        if not lead:
            raise ValueError("Lead not found")
        return deepcopy(lead)
    lead = _client(settings).table("leads").select("*").eq("id", lead_id).single().execute().data
    if not lead:
        raise ValueError("Lead not found")
    return lead


def _score(settings: Settings, lead_id: str) -> dict[str, Any] | None:
    if _uses_fallback(settings):
        return deepcopy(_FALLBACK_SCORES.get(lead_id))
    rows = (_client(settings).table("lead_scores")
        .select("score,disposition,tier,persona,evaluations,intent_score,intent_level,intent_reasons,scored_at")
        .eq("lead_id", lead_id).order("scored_at", desc=True).limit(1).execute().data or [])
    return rows[0] if rows else None


def _evidence(settings: Settings, lead_id: str) -> list[dict[str, Any]]:
    if _uses_fallback(settings):
        return deepcopy(_FALLBACK_EVIDENCE.get(lead_id, []))
    return (_client(settings).table("evidence")
        .select("id,title,source_url,publisher,excerpt,supports_fields,captured_at")
        .eq("lead_id", lead_id).order("captured_at", desc=True).limit(20).execute().data or [])


def _suppressed(settings: Settings, lead: dict[str, Any]) -> bool:
    email = str(lead.get("email") or "").strip().casefold()
    if not email:
        return False
    if _uses_fallback(settings):
        entries = [SuppressionEntry(id="local-suppression", email="suppressed@datamart.test",
            suppression_kind=SuppressionKind.MANUAL)]
        return is_suppressed(email, entries)
    rows = (_client(settings).table("suppression_entries")
        .select("id,email,suppression_kind,reason,source,is_active,created_by,created_at,updated_at")
        .eq("normalized_email", email).eq("is_active", True).limit(1).execute().data or [])
    return is_suppressed(email, [SuppressionEntry.model_validate(item) for item in rows])


def _assert_access(lead: dict[str, Any], actor_id: str, role: str) -> None:
    if role in {"admin", "manager"}:
        return
    if role == "sales" and str(lead.get("assigned_to") or "") == actor_id:
        return
    raise PermissionError("This lead is not assigned to the current sales user")


def _assert_eligible(settings: Settings, lead: dict[str, Any], actor_id: str, role: str) -> None:
    _assert_access(lead, actor_id, role)
    if lead.get("status") == "disqualified":
        raise ValueError("Lead is disqualified and cannot receive outreach")
    if not lead.get("sales_approved_at"):
        raise ValueError("Lead must be approved for sales before outreach generation")
    if _suppressed(settings, lead):
        raise PermissionError("Lead is suppressed and cannot receive outreach")


def _matched(score: dict[str, Any] | None) -> list[str]:
    output: list[str] = []
    for item in (score or {}).get("evaluations") or []:
        if isinstance(item, dict) and item.get("outcome") == "matched":
            label = item.get("label") or item.get("criterion") or item.get("key")
            if label:
                output.append(str(label))
    return output


def _generic(lead: dict[str, Any], channel: str) -> dict[str, Any]:
    person = str(lead.get("person_name") or "there").strip()
    company = str(lead.get("company_name") or "your company").strip()
    return {
        "subject": f"A quick question for {company}" if channel == "email" else None,
        "body": f"Hi {person},\n\nI’m reaching out from Datamart to see whether a brief conversation about your priorities at {company} would be useful. If it is relevant, I’d be happy to share a concise overview.\n\nBest,\nDatamart",
        "provider": "deterministic", "model": None, "evidence_refs": [],
        "grounding_status": "insufficient_evidence_generic",
        "grounding_warnings": ["No stored external evidence was available; only stored lead identity fields were used."],
        "generated_at": _now(),
    }


def _draft(settings: Settings, lead: dict[str, Any], score: dict[str, Any] | None, evidence: list[dict[str, Any]], channel: str) -> dict[str, Any]:
    if channel != "email":
        raise ValueError("Phase B outbound generation supports email; LinkedIn remains on the legacy copy-only workflow")
    if settings.aws_bearer_token_bedrock and settings.bedrock_model_id:
        result = BedrockClient(settings.aws_bearer_token_bedrock, settings.bedrock_model_id).generate_outreach_message(
            lead, evidence, icp_score=(score or {}).get("score"),
            icp_disposition=(score or {}).get("disposition"), matched_criteria=_matched(score),
            intent_score=(score or {}).get("intent_score"), intent_level=(score or {}).get("intent_level"),
            intent_signals=[str(item) for item in (score or {}).get("intent_reasons") or []],
        )
        return {**result, "grounding_status": result.get("evidence_coverage") or "partial"}
    if not evidence:
        return _generic(lead, channel)
    result = OutreachDraftEngine.draft(lead, evidence, channel=channel, persona=(score or {}).get("persona"))
    return {**result, "provider": "deterministic", "model": None,
        "evidence_refs": result.get("evidence_ids", []), "grounding_status": "grounded",
        "grounding_warnings": [], "generated_at": _now()}


def _validate(draft: dict[str, Any], evidence: list[dict[str, Any]], lead: dict[str, Any]) -> dict[str, Any]:
    subject, body = str(draft.get("subject") or "").strip(), str(draft.get("body") or "").strip()
    if not body or len(body) > 4000:
        raise ValueError("A concise outreach body is required")
    if len(subject) > 300:
        raise ValueError("Outreach subject exceeds 300 characters")
    stored_ids = {str(item["id"]) for item in evidence if item.get("id")}
    refs = [str(item) for item in draft.get("evidence_refs") or []]
    if any(item not in stored_ids for item in refs):
        raise ValueError("Generated outreach referenced evidence that is not stored for the lead")
    risky_claim = re.search(r"\b(?:raised|funded|funding|hiring|expanding|expanded|launched|revenue|employees|technology stack|pain point|initiative|growth|partnership|customers?|acquired)\b|\$\s?\d|\b\d+(?:\.\d+)?%", f"{subject}\n{body}", re.I)
    grounding_evidence = [item for item in evidence if str(item.get("id")) in refs]
    if grounding_evidence:
        validate_outreach_for_approval(f"{subject}\n{body}", grounding_evidence, lead)
    elif risky_claim:
        raise ValueError("Generic outreach contains a factual claim without stored evidence")
    return {"subject": subject or "Quick question", "body": body,
        "provider": str(draft.get("provider") or "unknown"),
        "model": str(draft["model"]) if draft.get("model") else None, "evidence_refs": refs,
        "grounding_status": str(draft.get("grounding_status") or ("grounded" if refs else "generic")),
        "grounding_warnings": [str(item) for item in draft.get("grounding_warnings") or []],
        "generated_at": str(draft.get("generated_at") or _now())}


def _metadata(draft: dict[str, Any]) -> dict[str, Any]:
    return {key: draft[key] for key in ("evidence_refs", "grounding_status", "grounding_warnings",
                                         "provider", "model", "generated_at")}


def _fallback_event(state: dict[str, Any], event_type: str, actor_id: str, payload: dict[str, Any]) -> None:
    state["events"].append({"id": f"event-{uuid4().hex}", "event_type": event_type,
        "event_payload": payload, "occurred_at": _now(), "created_by": actor_id})


def _fallback_persist(lead: dict[str, Any], draft: dict[str, Any], actor_id: str, regenerated: bool) -> dict[str, Any]:
    state = _FALLBACK_STATE.get(str(lead["id"]))
    now = _now()
    if state:
        if not regenerated:
            raise ValueError("An outreach draft already exists; use regenerate")
        message = state["latest_message"]
        if message["status"] != "draft" or state["lead_outreach"]["status"] == "sent":
            raise ValueError("Sent or finalized messages cannot be regenerated")
        message.update({"subject": draft["subject"], "body": draft["body"],
            "generation_provider": draft["provider"], "generation_model": draft["model"],
            "provider_response": _metadata(draft), "generated_at": draft["generated_at"],
            "updated_by": actor_id, "updated_at": now})
    else:
        outreach_id, message_id = f"outreach-{uuid4().hex}", f"message-{uuid4().hex}"
        state = {
            "lead_outreach": {"id": outreach_id, "lead_id": lead["id"], "sequence_id": "sequence-1",
                "status": "draft", "current_step_number": 1, "latest_message_id": message_id,
                "created_at": now, "updated_at": now},
            "latest_message": {"id": message_id, "lead_outreach_id": outreach_id,
                "sequence_step_id": "step-1", "step_number": 1, "direction": "outbound",
                "status": "draft", "subject": draft["subject"], "body": draft["body"],
                "generation_provider": draft["provider"], "generation_model": draft["model"],
                "provider_response": _metadata(draft), "generated_at": draft["generated_at"],
                "created_by": actor_id, "updated_by": actor_id, "created_at": now, "updated_at": now},
            "events": [],
        }
        _FALLBACK_STATE[str(lead["id"])] = state
    _fallback_event(state, "outreach_regenerated" if regenerated else "outreach_generated", actor_id, _metadata(draft))
    return state


def _db_state(settings: Settings, lead_id: str) -> dict[str, Any] | None:
    client = _client(settings)
    sequence = client.table("outreach_sequences").select("id").eq(
        "external_id", "datamart-outbound-sequence-v1").single().execute().data
    if not sequence:
        raise RuntimeError("The Phase A outreach sequence is not installed")
    rows = (client.table("lead_outreach").select("*").eq("lead_id", lead_id)
        .eq("sequence_id", sequence["id"]).limit(1).execute().data or [])
    if not rows:
        return None
    outreach = rows[0]
    messages = (client.table("outreach_messages").select("*").eq("lead_outreach_id", outreach["id"])
        .eq("direction", "outbound").order("created_at", desc=True).limit(1).execute().data or [])
    events = (client.table("outreach_events").select("*").eq("lead_outreach_id", outreach["id"])
        .order("occurred_at", desc=True).limit(30).execute().data or [])
    return {"lead_outreach": outreach, "latest_message": messages[0] if messages else None, "events": events}


def _db_event(settings: Settings, outreach_id: str, message_id: str, lead_id: str,
              actor_id: str, event_type: str, payload: dict[str, Any]) -> None:
    client = _client(settings)
    client.table("outreach_events").insert({"lead_outreach_id": outreach_id,
        "message_id": message_id, "event_type": event_type, "event_payload": payload,
        "created_by": actor_id}).execute()
    client.table("audit_log").insert({"actor_id": actor_id, "action": event_type,
        "entity_type": "outreach_message", "entity_id": message_id,
        "details": {"lead_id": lead_id, **payload}}).execute()


def _db_persist(settings: Settings, lead: dict[str, Any], draft: dict[str, Any],
                actor_id: str, regenerated: bool) -> dict[str, Any]:
    client = _client(settings)
    state, metadata = _db_state(settings, str(lead["id"])), _metadata(draft)
    if state:
        if not regenerated:
            raise ValueError("An outreach draft already exists; use regenerate")
        outreach, message = state["lead_outreach"], state["latest_message"]
        if not message or message.get("status") != "draft" or outreach.get("status") == "sent":
            raise ValueError("Sent or finalized messages cannot be regenerated")
        rows = (client.table("outreach_messages").update({"subject": draft["subject"],
            "body": draft["body"], "generation_provider": draft["provider"],
            "generation_model": draft["model"], "provider_response": metadata,
            "generated_at": draft["generated_at"], "updated_by": actor_id})
            .eq("id", message["id"]).eq("status", "draft").execute().data or [])
        if not rows:
            raise ValueError("Only a draft can be regenerated")
        message = rows[0]
    else:
        sequence = client.table("outreach_sequences").select("id").eq(
            "external_id", "datamart-outbound-sequence-v1").single().execute().data
        step = (client.table("outreach_sequence_steps").select("id").eq("sequence_id", sequence["id"])
            .eq("step_number", 1).single().execute().data)
        outreach = client.table("lead_outreach").insert({"lead_id": lead["id"],
            "sequence_id": sequence["id"], "status": "draft", "current_step_number": 1,
            "created_by": actor_id, "updated_by": actor_id}).execute().data[0]
        message = client.table("outreach_messages").insert({"lead_outreach_id": outreach["id"],
            "sequence_step_id": step["id"], "step_number": 1, "direction": "outbound",
            "status": "draft", "subject": draft["subject"], "body": draft["body"],
            "generation_provider": draft["provider"], "generation_model": draft["model"],
            "provider_response": metadata, "generated_at": draft["generated_at"],
            "idempotency_key": build_idempotency_key(lead_id=str(lead["id"]),
                sequence_id=str(sequence["id"]), step_number=1,
                recipient_email=str(lead.get("email") or ""), provider_name=draft["provider"]),
            "created_by": actor_id, "updated_by": actor_id}).execute().data[0]
        client.table("lead_outreach").update({"latest_message_id": message["id"],
            "updated_by": actor_id}).eq("id", outreach["id"]).execute()
    event_type = "outreach_regenerated" if regenerated else "outreach_generated"
    _db_event(settings, outreach["id"], message["id"], str(lead["id"]), actor_id, event_type, metadata)
    return _db_state(settings, str(lead["id"])) or {"lead_outreach": outreach, "latest_message": message, "events": []}


def _serialize(state: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(state)
    message = result.get("latest_message")
    if message:
        metadata = message.pop("provider_response", {}) or {}
        message.update({"provider": message.get("generation_provider"),
            "model": message.get("generation_model"),
            "evidence_refs": metadata.get("evidence_refs") or [],
            "grounding_status": metadata.get("grounding_status") or "unknown",
            "grounding_warnings": metadata.get("grounding_warnings") or []})
    return result


def list_outreach_leads(settings: Settings, actor_id: str, role: str) -> list[dict[str, Any]]:
    if _uses_fallback(settings):
        leads = [deepcopy(item) for item in _FALLBACK_LEADS.values()]
    else:
        query = (_client(settings).table("leads")
            .select("id,person_name,company_name,title,email,linkedin_url,company_url,country,industry,status,assigned_to,sales_approved_at")
            .not_.is_("sales_approved_at", "null").neq("status", "disqualified"))
        if role == "sales":
            query = query.eq("assigned_to", actor_id)
        leads = query.order("sales_approved_at", desc=True).limit(100).execute().data or []
    output: list[dict[str, Any]] = []
    for lead in leads:
        if not lead.get("sales_approved_at") or lead.get("status") == "disqualified":
            continue
        try:
            _assert_access(lead, actor_id, role)
        except PermissionError:
            continue
        state = _FALLBACK_STATE.get(str(lead["id"])) if _uses_fallback(settings) else _db_state(settings, str(lead["id"]))
        latest = _serialize(state).get("latest_message") if state else None
        output.append({**lead, "score": _score(settings, str(lead["id"])),
            "suppressed": _suppressed(settings, lead),
            "outreach_status": (state or {}).get("lead_outreach", {}).get("status", "none"),
            "latest_draft_status": (latest or {}).get("status")})
    return output


def generate_outreach_message(settings: Settings, actor_id: str, role: str, lead_id: str,
                              *, channel: str = "email") -> dict[str, Any]:
    lead = _lead(settings, lead_id)
    _assert_eligible(settings, lead, actor_id, role)
    evidence, score = _evidence(settings, lead_id), _score(settings, lead_id)
    draft = _validate(_draft(settings, lead, score, evidence, channel), evidence, lead)
    state = (_fallback_persist(lead, draft, actor_id, False) if _uses_fallback(settings)
             else _db_persist(settings, lead, draft, actor_id, False))
    serialized, message = _serialize(state), _serialize(state)["latest_message"]
    return {"lead_id": lead_id, "lead_outreach_id": serialized["lead_outreach"]["id"],
        "message_id": message["id"], "status": message["status"], "subject": message["subject"],
        "body": message["body"], "provider": message["provider"], "model": message["model"],
        "evidence_refs": message["evidence_refs"], "generated_at": message["generated_at"],
        "grounding_status": message["grounding_status"],
        "grounding_warnings": message["grounding_warnings"]}


def get_outreach_state(settings: Settings, actor_id: str, role: str, lead_id: str) -> dict[str, Any]:
    lead = _lead(settings, lead_id)
    _assert_access(lead, actor_id, role)
    state = _FALLBACK_STATE.get(lead_id) if _uses_fallback(settings) else _db_state(settings, lead_id)
    serialized = _serialize(state) if state else {}
    return {"lead": lead, "score": _score(settings, lead_id),
        "lead_outreach": serialized.get("lead_outreach"),
        "latest_message": serialized.get("latest_message"),
        "status": serialized.get("lead_outreach", {}).get("status", "none"),
        "suppressed": _suppressed(settings, lead), "evidence": _evidence(settings, lead_id),
        "events": serialized.get("events", [])}


def save_outreach_draft(settings: Settings, actor_id: str, role: str, lead_id: str,
                        *, subject: str, body: str) -> dict[str, Any]:
    lead = _lead(settings, lead_id)
    _assert_eligible(settings, lead, actor_id, role)
    state = _FALLBACK_STATE.get(lead_id) if _uses_fallback(settings) else _db_state(settings, lead_id)
    if not state or not state.get("latest_message"):
        raise ValueError("No outreach draft exists for this lead")
    message, outreach = state["latest_message"], state["lead_outreach"]
    if message.get("status") != "draft" or outreach.get("status") == "sent":
        raise ValueError("Sent or finalized messages cannot be edited")
    evidence = _evidence(settings, lead_id)
    metadata = message.get("provider_response") or {}
    candidate = _validate({"subject": subject, "body": body,
        "provider": message.get("generation_provider"), "model": message.get("generation_model"),
        **metadata, "generated_at": message.get("generated_at")}, evidence, lead)
    event_payload = {"changed_fields": ["subject", "body"]}
    if _uses_fallback(settings):
        message.update({"subject": candidate["subject"], "body": candidate["body"],
            "updated_by": actor_id, "updated_at": _now()})
        for event_type in ("outreach_edited", "outreach_saved"):
            _fallback_event(state, event_type, actor_id, event_payload)
        return _serialize(state)
    rows = (_client(settings).table("outreach_messages").update({"subject": candidate["subject"],
        "body": candidate["body"], "updated_by": actor_id}).eq("id", message["id"])
        .eq("status", "draft").execute().data or [])
    if not rows:
        raise ValueError("Only a draft can be edited")
    for event_type in ("outreach_edited", "outreach_saved"):
        _db_event(settings, outreach["id"], message["id"], lead_id, actor_id, event_type, event_payload)
    return get_outreach_state(settings, actor_id, role, lead_id)


def regenerate_outreach(settings: Settings, actor_id: str, role: str, lead_id: str) -> dict[str, Any]:
    lead = _lead(settings, lead_id)
    _assert_eligible(settings, lead, actor_id, role)
    state = _FALLBACK_STATE.get(lead_id) if _uses_fallback(settings) else _db_state(settings, lead_id)
    if not state or not state.get("latest_message"):
        raise ValueError("No outreach draft exists for this lead")
    if state["latest_message"].get("status") != "draft" or state["lead_outreach"].get("status") == "sent":
        raise ValueError("Sent or finalized messages cannot be regenerated")
    evidence, score = _evidence(settings, lead_id), _score(settings, lead_id)
    draft = _validate(_draft(settings, lead, score, evidence, "email"), evidence, lead)
    return _serialize(_fallback_persist(lead, draft, actor_id, True) if _uses_fallback(settings)
                      else _db_persist(settings, lead, draft, actor_id, True))
