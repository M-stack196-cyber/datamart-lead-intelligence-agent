from app.workers.queue import InMemoryJobQueue, JobStatus
import pytest

from app.workers.runner import (
    _complete_job,
    approved_run_limit,
    build_enrichment_intelligence,
    process_next_job,
)


class FakeProvider:
    def enrich(self, lead):
        return type(
            "Result",
            (),
            {
                "matched": True,
                "fields": {"person_name": "Aisha Rafiq"},
                "evidence": [
                    {
                        "title": "Hiring expansion",
                        "source_url": "https://example.com/hiring",
                        "evidence_type": "job_post",
                        "publisher": "Example",
                        "excerpt": "Hiring for GTM roles",
                        "supports_fields": ["person_name"],
                        "metadata": {"confidence": 0.9},
                    }
                ],
                "prospect_id": "prospect-123",
                "raw_result": {"provider": "fake"},
            },
        )()


class FakeRpcClient:
    def __init__(self) -> None:
        self.name = ""
        self.payload = {}

    def rpc(self, name, payload):
        self.name = name
        self.payload = payload
        return self

    def execute(self):
        return type("Response", (), {"data": {"lead_status": "nurture"}})()


def test_process_next_job_updates_queue_result_for_enrichment() -> None:
    queue = InMemoryJobQueue()
    job = queue.enqueue("lead-42", "enrich", {"source": "live_capture", "lead": {"id": "lead-42", "company_name": "Datamart"}})

    processed = process_next_job(queue, FakeProvider(), worker_name="worker-a")

    assert processed is True
    stored = queue.get(job.id)
    assert stored.status == JobStatus.COMPLETED
    assert stored.result["matched"] is True
    assert stored.result["updated_fields"] == ["person_name"]
    assert stored.result["evidence_count"] == 1
    assert stored.result["icp_score"] >= 0
    assert stored.result["intent_level"] in {"low", "medium", "high"}
    assert "raw_result" not in stored.result


def test_database_pipeline_completes_through_one_atomic_rpc_without_raw_payload() -> None:
    client = FakeRpcClient()
    enrichment = FakeProvider().enrich({})

    result = _complete_job(
        client,
        {"id": "00000000-0000-0000-0000-000000000042", "lead_id": "lead-42"},
        {"id": "lead-42", "company_name": "Datamart"},
        enrichment,
    )

    assert result == {"lead_status": "nurture"}
    assert client.name == "complete_enrichment_intelligence_job"
    assert client.payload["provider_fields"] == {"person_name": "Aisha Rafiq"}
    assert client.payload["provider_evidence"][0]["evidence_type"] == "job_page"
    assert "raw_result" not in client.payload["provider_result"]
    assert client.payload["score_result"]["icp_version"] == 2


def test_pipeline_marks_outside_geography_for_review_without_a_hard_stop() -> None:
    enrichment = FakeProvider().enrich({})
    enrichment.fields.update(
        {
            "company_name": "Pakistan SaaS",
            "title": "CTO",
            "country": "Pakistan",
            "industry": "SaaS",
        }
    )
    lead = {
        "company_name": "Human-entered company",
        "annual_revenue": 2_000_000,
        "employee_count": 20,
        "business_model": "SaaS",
        "growth_stage": "Post-PMF",
        "buying_behavior": "Retainer-ready",
        "has_defined_software_need": True,
        "accepts_distributed_delivery": True,
    }

    result = build_enrichment_intelligence(lead, enrichment)

    assert result.score.disposition == "Opportunistic / Manual Review"
    assert result.score.hard_stops == []
    assert result.score.review_reasons
    assert result.lead_status == "review"


def test_pipeline_no_match_and_missing_evidence_remain_unknown_and_nurture() -> None:
    enrichment = type(
        "NoMatch",
        (),
        {"matched": False, "fields": {}, "evidence": [], "prospect_id": None},
    )()

    result = build_enrichment_intelligence(
        {"company_name": "Unknown Company"}, enrichment
    )

    assert result.evidence == []
    assert result.intent.level == "low"
    assert result.intent.evidence_urls == []
    assert result.score.evidence_urls == []
    assert all(item.outcome == "unknown" for item in result.score.evaluations)
    assert result.lead_status == "nurture"


def test_pipeline_preserves_hard_stops_and_filters_blank_or_duplicate_provider_data() -> None:
    enrichment = type(
        "DuplicateResult",
        (),
        {
            "matched": True,
            "fields": {"company_name": "  ", "title": "Founder", "status": "qualified"},
            "evidence": [
                {"title": "Funding", "source_url": "https://example.com/funding"},
                {"title": "Funding duplicate", "source_url": "https://example.com/funding#top"},
                {"title": "Unsupported", "source_url": "javascript:alert(1)"},
            ],
            "prospect_id": "prospect-duplicate",
        },
    )()

    result = build_enrichment_intelligence(
        {
            "company_name": "Human Company",
            "annual_revenue": 100_000,
            "business_model": "SaaS",
        },
        enrichment,
    )

    assert result.provider_fields == {"title": "Founder"}
    assert len(result.evidence) == 1
    assert result.score.hard_stops == ["Annual revenue is below $500K."]
    assert result.lead_status == "disqualified"


def test_worker_limit_cannot_exceed_explicit_approval() -> None:
    assert approved_run_limit(None, 1) == 1
    assert approved_run_limit(2, 3) == 2
    with pytest.raises(ValueError, match="exceeds VIBE_APPROVED_JOB_LIMIT"):
        approved_run_limit(4, 3)
