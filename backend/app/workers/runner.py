"""Explicit, single-job Vibe enrichment worker. Run only after reviewing provider cost."""

import argparse
from datetime import datetime, timezone
from typing import Any

from supabase import create_client

from app.core.config import get_settings
from app.integrations.vibe import VibeProspectingClient
from app.workers.queue import InMemoryJobQueue, JobStatus


def _service_client():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for the worker")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _claim_job(client: Any, worker_name: str) -> dict[str, Any] | None:
    return client.rpc("claim_next_enrichment_job", {"worker_name": worker_name}).execute().data


def _complete_job(client: Any, job: dict[str, Any], enrichment: Any) -> None:
    lead_id = job["lead_id"]
    if enrichment.matched and enrichment.fields:
        client.table("leads").update(enrichment.fields).eq("id", lead_id).execute()
    for item in enrichment.evidence:
        client.table("evidence").insert({"lead_id": lead_id, "evidence_type": item.evidence_type, "title": item.title, "source_url": item.source_url, "publisher": item.publisher, "excerpt": item.excerpt, "supports_fields": item.supports_fields, "metadata": item.metadata}).execute()
    client.table("processing_jobs").update({"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat(), "result": {"provider": "agentsource", "matched": enrichment.matched, "prospect_id": enrichment.prospect_id, "updated_fields": sorted(enrichment.fields), "evidence_count": len(enrichment.evidence), "raw_result": enrichment.raw_result}, "error_message": None}).eq("id", job["id"]).execute()


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
        fields = getattr(enrichment, "fields", {}) or {}
        evidence = getattr(enrichment, "evidence", []) or []
        result = {
            "provider": "agentsource",
            "matched": bool(getattr(enrichment, "matched", False)),
            "prospect_id": getattr(enrichment, "prospect_id", None),
            "updated_fields": sorted(fields),
            "evidence_count": len(evidence),
            "raw_result": getattr(enrichment, "raw_result", {}),
        }
        if getattr(enrichment, "matched", False) and fields:
            result["updated_fields"] = sorted(fields)
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
        _complete_job(client, job, enrichment)
    except Exception as exc:
        _fail_job(client, job, exc)
        raise
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process approved Vibe enrichment jobs")
    parser.add_argument("--limit", type=int, default=1, help="Maximum queued jobs; default is one")
    args = parser.parse_args()
    for _ in range(max(1, args.limit)):
        if not run_once():
            print("No queued Vibe enrichment jobs.")
            return
    print("Vibe enrichment job completed.")


if __name__ == "__main__":
    main()


