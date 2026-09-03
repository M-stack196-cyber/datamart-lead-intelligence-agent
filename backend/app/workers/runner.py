"""Explicit, single-job Vibe enrichment worker. Run only after reviewing provider cost."""

import argparse
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from supabase import create_client

from app.core.config import get_settings
from app.integrations.vibe import VibeProspectingClient
from app.intent import IntentEngine, IntentScore
from app.repositories.icp_repository import icp_repository
from app.schemas.icp import ScoreResult, LeadProfile
from app.scoring.icp_engine import IcpScoringEngine
from app.workers.queue import InMemoryJobQueue


SAFE_PROVIDER_FIELDS = {
    "company_name",
    "person_name",
    "title",
    "country",
    "industry",
    "email",
}
ALLOWED_EVIDENCE_TYPES = {
    "linkedin_post",
    "company_page",
    "job_page",
    "news",
    "search_result",
    "other",
}


@dataclass(frozen=True)
class EnrichmentIntelligence:
    provider_fields: dict[str, Any]
    evidence: list[dict[str, Any]]
    score: ScoreResult
    intent: IntentScore
    lead_status: str


def _service_client():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for the worker")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _claim_job(client: Any, worker_name: str) -> dict[str, Any] | None:
    return client.rpc("claim_next_enrichment_job", {"worker_name": worker_name}).execute().data


def _provider_fields(enrichment: Any) -> dict[str, Any]:
    fields = getattr(enrichment, "fields", {}) or {}
    if not isinstance(fields, dict):
        return {}
    return {
        key: value
        for key, value in fields.items()
        if key in SAFE_PROVIDER_FIELDS
        and value is not None
        and (not isinstance(value, str) or value.strip())
    }


def _evidence_dict(item: Any) -> dict[str, Any] | None:
    value = item if isinstance(item, dict) else asdict(item)
    source_url = value.get("source_url")
    title = value.get("title")
    if not isinstance(source_url, str) or not isinstance(title, str):
        return None
    source_url = source_url.strip().split("#", 1)[0].rstrip("/")
    parsed = urlparse(source_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not title.strip():
        return None
    evidence_type = str(value.get("evidence_type") or "other")
    if evidence_type == "job_post":
        evidence_type = "job_page"
    if evidence_type not in ALLOWED_EVIDENCE_TYPES:
        evidence_type = "other"
    supports_fields = value.get("supports_fields")
    metadata = value.get("metadata")
    return {
        "title": title.strip(),
        "source_url": source_url,
        "evidence_type": evidence_type,
        "publisher": value.get("publisher"),
        "excerpt": value.get("excerpt"),
        "supports_fields": supports_fields if isinstance(supports_fields, list) else [],
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _provider_evidence(enrichment: Any) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    evidence: list[dict[str, Any]] = []
    for raw in getattr(enrichment, "evidence", []) or []:
        item = _evidence_dict(raw)
        if item is None:
            continue
        key = (item["evidence_type"], item["source_url"].casefold())
        if key in seen:
            continue
        seen.add(key)
        evidence.append(item)
    return evidence


def build_enrichment_intelligence(lead: dict[str, Any], enrichment: Any) -> EnrichmentIntelligence:
    fields = _provider_fields(enrichment)
    evidence = _provider_evidence(enrichment)
    normalized_lead = {**lead, **fields}
    score = IcpScoringEngine(icp_repository.get_active()).score(
        LeadProfile.model_validate(
            {**normalized_lead, "evidence_urls": [item["source_url"] for item in evidence]}
        )
    )
    intent = IntentEngine.score(normalized_lead, evidence)
    if score.hard_stops:
        lead_status = "disqualified"
    elif score.disposition == "Not Qualified" and intent.level == "low":
        lead_status = "nurture"
    else:
        lead_status = "review"
    return EnrichmentIntelligence(fields, evidence, score, intent, lead_status)


def _complete_job(
    client: Any, job: dict[str, Any], lead: dict[str, Any], enrichment: Any
) -> dict[str, Any]:
    intelligence = build_enrichment_intelligence(lead, enrichment)
    provider_result = {
        "provider": "agentsource",
        "matched": bool(getattr(enrichment, "matched", False)),
        "prospect_id": getattr(enrichment, "prospect_id", None),
        "updated_fields": sorted(intelligence.provider_fields),
        "evidence_count": len(intelligence.evidence),
    }
    payload = {
        "target_job_id": job["id"],
        "provider_fields": intelligence.provider_fields,
        "provider_evidence": intelligence.evidence,
        "score_result": intelligence.score.model_dump(mode="json"),
        "intent_result": asdict(intelligence.intent),
        "provider_result": provider_result,
    }
    return client.rpc("complete_enrichment_intelligence_job", payload).execute().data


def _fail_job(client: Any, job: dict[str, Any], error: Exception) -> None:
    status = "failed" if int(job["attempts"]) >= int(job["max_attempts"]) else "queued"
    client.table("processing_jobs").update({"status": status, "error_message": str(error)[:1000], "claimed_at": None, "claimed_by": None}).eq("id", job["id"]).execute()


def process_next_job(queue: InMemoryJobQueue, provider: Any, *, worker_name: str = "local-vibe-worker") -> bool:
    job = queue.claim_next(worker_name)
    if job is None:
        return False

    try:
        lead = job.payload.get("lead", {}) if isinstance(job.payload, dict) else {}
        enrichment = provider.enrich(lead)
        intelligence = build_enrichment_intelligence(lead, enrichment)
        result = {
            "provider": "agentsource",
            "matched": bool(getattr(enrichment, "matched", False)),
            "prospect_id": getattr(enrichment, "prospect_id", None),
            "updated_fields": sorted(intelligence.provider_fields),
            "evidence_count": len(intelligence.evidence),
            "icp_score": intelligence.score.score,
            "disposition": intelligence.score.disposition,
            "intent_score": intelligence.intent.score,
            "intent_level": intelligence.intent.level,
            "lead_status": intelligence.lead_status,
        }
        queue.complete_job(job.id, result)
    except Exception as exc:
        queue.fail_job(job.id, exc)
        raise
    return True


def run_once() -> bool:
    settings = get_settings()
    if not settings.vibe_enrichment_enabled:
        raise RuntimeError("Set VIBE_ENRICHMENT_ENABLED=true only after approving the AgentSource cost estimate")
    if not settings.vibe_api_key:
        raise RuntimeError("VIBE_API_KEY is required")
    client = _service_client()
    job = _claim_job(client, settings.vibe_worker_name)
    if not job:
        return False
    try:
        lead = client.table("leads").select("*").eq("id", job["lead_id"]).single().execute().data
        enrichment = VibeProspectingClient(settings.vibe_api_key, settings.vibe_api_base_url).enrich(lead)
        _complete_job(client, job, lead, enrichment)
    except Exception as exc:
        _fail_job(client, job, exc)
        raise
    return True


def approved_run_limit(requested: int | None, approved: int) -> int:
    limit = approved if requested is None else requested
    if limit < 1:
        raise ValueError("Worker limit must be at least one")
    if limit > approved:
        raise ValueError(
            f"Requested worker limit {limit} exceeds VIBE_APPROVED_JOB_LIMIT={approved}"
        )
    return limit


def main() -> None:
    parser = argparse.ArgumentParser(description="Process approved Vibe enrichment jobs")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum queued jobs; cannot exceed VIBE_APPROVED_JOB_LIMIT",
    )
    args = parser.parse_args()
    settings = get_settings()
    limit = approved_run_limit(args.limit, settings.vibe_approved_job_limit)
    for _ in range(limit):
        if not run_once():
            print("No queued Vibe enrichment jobs.")
            return
    print("Vibe enrichment job completed.")


if __name__ == "__main__":
    main()
