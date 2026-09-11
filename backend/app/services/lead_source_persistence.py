from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from supabase import create_client

from app.core.config import Settings, get_settings
from app.services.lead_source_ingestion import LeadSourceIngestionResult
from app.services.vibe_identity import normalized_id, normalized_name, normalized_url
from app.services.vibe_icp_pipeline import ScoredProspect


SUPABASE_PERSISTENCE_NOT_CONFIGURED = (
    "Supabase persistence is not configured. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
)


@dataclass(frozen=True)
class GenericLeadPersistenceResult:
    inserted_count: int
    updated_count: int
    duplicate_count: int
    lead_score_count: int
    warnings: list[str]
    errors: list[str]


def service_role_client(settings: Settings | None = None) -> Any:
    settings = settings or get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(SUPABASE_PERSISTENCE_NOT_CONFIGURED)
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def persist_scored_leads(
    client: Any,
    result: LeadSourceIngestionResult,
    *,
    file_name: str = "generic-lead-source-import",
) -> GenericLeadPersistenceResult:
    if not result.scored:
        return GenericLeadPersistenceResult(0, 0, result.duplicate_count, 0, [], result.errors)

    active_icp = _active_icp_version(client)
    if not active_icp.get("id"):
        raise RuntimeError("No active ICP version found")

    import_id = _create_import(client, file_name, result)
    inserted = 0
    updated = 0
    scores = 0
    warnings = list(result.warnings)
    errors = list(result.errors)
    seen: set[tuple[str, ...]] = set()
    local_duplicates = 0

    for item in result.scored:
        identities = _prospect_identities(item.prospect)
        if identities & seen:
            seen.update(identities)
            local_duplicates += 1
            continue
        seen.update(identities)

        try:
            existing = _find_existing_lead(client, item.prospect)
            if existing:
                lead = _update_lead(client, existing, item)
                updated += 1
            else:
                lead = _insert_lead(client, import_id, item)
                inserted += 1

            lead_id = lead.get("id")
            if not lead_id:
                errors.append("A persisted lead did not return an id")
                continue

            _insert_score(client, str(lead_id), str(active_icp["id"]), item)
            scores += 1
        except Exception as exc:
            errors.append(
                f"{item.prospect.get('person_name') or item.prospect.get('company_name') or 'Lead'} "
                f"could not be persisted: {type(exc).__name__}"
            )

    _complete_import(client, import_id, inserted + updated, len(errors))
    _audit_import(client, import_id, inserted, updated, result.duplicate_count + local_duplicates)

    return GenericLeadPersistenceResult(
        inserted_count=inserted,
        updated_count=updated,
        duplicate_count=result.duplicate_count + local_duplicates,
        lead_score_count=scores,
        warnings=warnings,
        errors=errors,
    )


def _active_icp_version(client: Any) -> dict[str, Any]:
    rows = (
        client.table("icp_versions")
        .select("id,external_id,version")
        .eq("status", "active")
        .order("version", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def _create_import(
    client: Any,
    file_name: str,
    result: LeadSourceIngestionResult,
) -> str | None:
    rows = (
        client.table("imports")
        .insert(
            {
                "file_name": file_name[:255] or "generic-lead-source-import",
                "source": "csv",
                "status": "processing",
                "total_rows": result.requested_count,
                "accepted_rows": 0,
                "rejected_rows": 0,
                "created_by": None,
            }
        )
        .execute()
        .data
        or []
    )
    return rows[0].get("id") if rows else None


def _complete_import(client: Any, import_id: str | None, accepted: int, rejected: int) -> None:
    if not import_id:
        return
    (
        client.table("imports")
        .update(
            {
                "status": "completed",
                "accepted_rows": accepted,
                "rejected_rows": rejected,
                "completed_at": _now(),
            }
        )
        .eq("id", import_id)
        .execute()
    )


def _audit_import(
    client: Any,
    import_id: str | None,
    inserted: int,
    updated: int,
    duplicates: int,
) -> None:
    if not import_id:
        return
    (
        client.table("audit_log")
        .insert(
            {
                "actor_id": None,
                "action": "generic_lead_source_imported",
                "entity_type": "import",
                "entity_id": import_id,
                "details": {
                    "inserted": inserted,
                    "updated": updated,
                    "duplicates": duplicates,
                },
            }
        )
        .execute()
    )


def _find_existing_lead(client: Any, prospect: dict[str, Any]) -> dict[str, Any] | None:
    for column, value in _identity_queries(prospect):
        query = client.table("leads").select("*")
        for key, expected in column:
            query = query.eq(key, expected)
        rows = query.order("created_at").limit(1).execute().data or []
        if rows:
            return rows[0]
    return None


def _identity_queries(
    prospect: dict[str, Any],
) -> list[tuple[list[tuple[str, str]], str]]:
    queries: list[tuple[list[tuple[str, str]], str]] = []
    if email := _lower_string(prospect.get("email")):
        queries.append(([("email", email)], email))
    if linkedin := _string(prospect.get("linkedin_url")):
        queries.append(([("linkedin_url", linkedin)], linkedin))
    source = _string(prospect.get("lead_source"))
    source_id = _string(prospect.get("source_id"))
    if source and source_id:
        queries.append(
            (
                [
                    ("lead_source", source),
                    ("source_id", source_id),
                ],
                f"{source}:{source_id}",
            )
        )
    company_url = _string(prospect.get("company_url"))
    person_name = _string(prospect.get("person_name"))
    if company_url and person_name:
        queries.append(
            (
                [
                    ("company_url", company_url),
                    ("person_name", person_name),
                ],
                f"{company_url}:{person_name}",
            )
        )
    return queries


def _insert_lead(client: Any, import_id: str | None, item: ScoredProspect) -> dict[str, Any]:
    rows = (
        client.table("leads")
        .insert(_lead_payload(item, import_id=import_id))
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def _update_lead(
    client: Any,
    existing: dict[str, Any],
    item: ScoredProspect,
) -> dict[str, Any]:
    payload = _lead_payload(item, import_id=existing.get("import_id"))
    payload.pop("created_by", None)
    payload.pop("import_id", None)
    payload = {key: value for key, value in payload.items() if value is not None}
    payload["raw_source_data"] = {
        **(existing.get("raw_source_data") if isinstance(existing.get("raw_source_data"), dict) else {}),
        **payload["raw_source_data"],
    }
    rows = (
        client.table("leads")
        .update(payload)
        .eq("id", existing["id"])
        .execute()
        .data
        or []
    )
    return rows[0] if rows else existing


def _lead_payload(
    item: ScoredProspect,
    *,
    import_id: str | None,
) -> dict[str, Any]:
    prospect = item.prospect
    return {
        "import_id": import_id,
        "created_by": None,
        "company_name": _string(prospect.get("company_name")),
        "person_name": _string(prospect.get("person_name")),
        "title": _string(prospect.get("title")),
        "linkedin_url": _string(prospect.get("linkedin_url")),
        "company_url": _string(prospect.get("company_url")),
        "email": _lower_string(prospect.get("email")),
        "phone": _string(prospect.get("phone")),
        "country": _string(prospect.get("country")),
        "industry": _string(prospect.get("industry")),
        "employee_count": _int(prospect.get("employee_count")),
        "status": _lead_status(item),
        "raw_source_data": _raw_source_data(prospect, item.pipeline_status),
        "lead_source": _string(prospect.get("lead_source")),
        "source_id": _string(prospect.get("source_id")),
        "source_captured_at": _now(),
    }


def _insert_score(
    client: Any,
    lead_id: str,
    icp_version_id: str,
    item: ScoredProspect,
) -> None:
    score = item.score
    payload = score.model_dump(mode="json")
    (
        client.table("lead_scores")
        .insert(
            {
                "lead_id": lead_id,
                "icp_version_id": icp_version_id,
                "score": score.score,
                "disposition": _db_disposition(score.disposition),
                "tier": score.tier,
                "persona": score.persona,
                "hard_stops": payload.get("hard_stops") or [],
                "review_reasons": payload.get("review_reasons") or [],
                "evaluations": payload.get("evaluations") or [],
                "evidence_ids": [],
                "intent_score": 0,
                "intent_level": "low",
                "intent_reasons": [],
                "scored_by": None,
            }
        )
        .execute()
    )


def _lead_status(item: ScoredProspect) -> str:
    if item.score.hard_stops or item.pipeline_status == "rejected":
        return "disqualified"
    return "review"


def _db_disposition(disposition: str) -> str:
    if disposition == "Opportunistic / Manual Review":
        return "Review"
    return disposition


def _raw_source_data(prospect: dict[str, Any], pipeline_status: str) -> dict[str, Any]:
    raw = prospect.get("raw_source_data")
    payload = raw if isinstance(raw, dict) else {}
    return {
        **payload,
        "source": prospect.get("lead_source"),
        "source_id": prospect.get("source_id"),
        "pipeline_status": pipeline_status,
    }


def _prospect_identities(prospect: dict[str, Any]) -> set[tuple[str, ...]]:
    identities: set[tuple[str, ...]] = set()
    if email := normalized_id(prospect.get("email")):
        identities.add(("email", email))
    if linkedin := normalized_url(prospect.get("linkedin_url")):
        identities.add(("linkedin", linkedin))
    source = normalized_id(prospect.get("lead_source"))
    source_id = normalized_id(prospect.get("source_id"))
    if source and source_id:
        identities.add(("source", source, source_id))
    company_url = normalized_url(prospect.get("company_url"))
    person = normalized_name(prospect.get("person_name"))
    if company_url and person:
        identities.add(("website_person", company_url, person))
    return identities


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _lower_string(value: Any) -> str | None:
    text = _string(value)
    return text.casefold() if text else None


def _int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return None
