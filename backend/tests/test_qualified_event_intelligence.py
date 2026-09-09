from dataclasses import replace

from app.integrations.vibe.events import (
    VibeBusinessEvent,
)
from app.services.qualified_event_intelligence import (
    enrich_qualified_with_events,
)
from app.services.vibe_icp_pipeline import (
    ScoredDiscoveryBatch,
    score_prospect,
)


class FakeEventsClient:
    def __init__(self):
        self.calls = []

    def fetch_business_events(
        self,
        business_ids,
        *,
        event_types=None,
        timestamp_from=None,
    ):
        self.calls.append(
            {
                "business_ids": business_ids,
                "timestamp_from": (
                    timestamp_from
                ),
            }
        )

        return [
            VibeBusinessEvent(
                business_id="business-1",
                event_id="event-1",
                event_type=(
                    "new_funding_round"
                ),
                title=(
                    "Company raises funding"
                ),
                occurred_at=(
                    "2026-09-03T12:00:00Z"
                ),
                source_url=(
                    "https://example.com/"
                    "funding"
                ),
                excerpt=(
                    "Company announced "
                    "new funding."
                ),
                raw_data={},
            )
        ]


def qualified_prospect():
    prospect = {
        "person_name": "Jane Founder",
        "linkedin_url": "https://linkedin.com/in/jane",
        "company_name": "Cloud Labs",
        "company_url": "https://cloudlabs.example",
        "company_type": "privately held",
        "title": "Founder",
        "country": "United States",
        "industry": "SaaS",
        "annual_revenue": 2_000_000,
        "employee_count": 20,
        "growth_stage": "Revenue",
        "business_model": "B2B SaaS",
        "buying_behavior": "Milestone SOW",
        "has_defined_software_need": True,
        "accepts_distributed_delivery": True,
        "vibe_business_id": "business-1",
        "email": "jane@example.com",
    }

    result = score_prospect(
        prospect
    )

    assert (
        result.pipeline_status
        == "qualified"
    )

    return result


def test_qualified_prospect_gets_events():
    batch = ScoredDiscoveryBatch(
        qualified=[
            qualified_prospect()
        ],
        needs_review=[],
        rejected=[],
    )

    client = FakeEventsClient()

    results = enrich_qualified_with_events(
        batch,
        client,
        timestamp_from="2026-08-01",
    )

    assert len(results) == 1

    result = results[0]

    assert (
        result.business_id
        == "business-1"
    )

    assert len(result.events) == 1
    assert len(result.evidence) == 1

    assert (
        result.evidence[0][
            "intent_signal"
        ]
        == "funding"
    )

    assert result.intent.score > 0

    assert len(client.calls) == 1


def test_no_qualified_prospects_skips_api():
    batch = ScoredDiscoveryBatch(
        qualified=[],
        needs_review=[],
        rejected=[],
    )

    client = FakeEventsClient()

    results = enrich_qualified_with_events(
        batch,
        client,
    )

    assert results == []
    assert client.calls == []


def test_only_accepted_prospects_are_kept_for_persistence():
    qualified = qualified_prospect()
    batch = ScoredDiscoveryBatch(
        qualified=[qualified],
        needs_review=[replace(qualified, pipeline_status="needs_review")],
        rejected=[replace(qualified, pipeline_status="rejected")],
    )

    results = enrich_qualified_with_events(batch, FakeEventsClient())

    assert len(results) == 2
    assert {item.scored_prospect.pipeline_status for item in results} == {
        "qualified",
        "needs_review",
    }
