from dataclasses import replace
from pathlib import Path

import pytest

from app.integrations.vibe.events import (
    VibeBusinessEvent,
)
from app.services.qualified_event_intelligence import (
    QualifiedProspectIntelligence,
)
from app.services.vibe_discovery_persistence import (
    _match_stored_lead,
    persist_discovery_intelligence,
    persist_qualified_intelligence,
)
from app.services.vibe_icp_pipeline import (
    score_prospect,
)
from app.intent import IntentEngine


class Result:
    def __init__(self, data):
        self.data = data


class RpcCall:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return Result(self.data)


class FakeClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append(
            {
                "name": name,
                "payload": payload,
            }
        )

        if (
            name
            == "ingest_vibe_discovered_leads"
        ):
            return RpcCall(
                {
                    "leads": [
                        {
                            "lead_id": "lead-1",
                            "linkedin_url": (
                                "https://linkedin.com/"
                                "in/jane"
                            ),
                            "email": (
                                "jane@example.com"
                            ),
                            "vibe_business_id": (
                                "business-1"
                            ),
                        }
                    ]
                }
            )

        if (
            name
            == "persist_vibe_discovery_intelligence"
        ):
            return RpcCall(
                {
                    "lead_id": "lead-1",
                    "status": "review",
                    "evidence_count": 1,
                    "evidence_ids": ["evidence-1"],
                }
            )

        if name == "create_automatic_vibe_outreach_draft":
            return RpcCall({"id": "draft-1", "status": "draft"})

        raise AssertionError(
            f"Unexpected RPC: {name}"
        )


def intelligence_item():
    prospect = {
        "person_name": "Jane",
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
        "linkedin_url": (
            "https://linkedin.com/in/jane"
        ),
        "email": "jane@example.com",
        "vibe_business_id": "business-1",
    }

    scored = score_prospect(
        prospect
    )

    event = VibeBusinessEvent(
        business_id="business-1",
        event_id="event-1",
        event_type="new_funding_round",
        title="Funding announcement",
        occurred_at="2026-09-03T12:00:00Z",
        source_url="https://example.com/funding",
        excerpt="Company raised funding.",
        raw_data={},
    )

    evidence = [
        {
            "evidence_type": "other",
            "title": event.title,
            "source_url": event.source_url,
            "publisher": "Explorium AgentSource",
            "activity_at": event.occurred_at,
            "intent_signal": "funding",
            "intent_reason": (
                "Recent funding may increase "
                "software buying capacity."
            ),
            "intent_score_delta": 20,
            "supports_fields": [
                "company_activity",
                "intent",
            ],
            "metadata": {
                "event_id": event.event_id,
            },
        }
    ]

    intent = IntentEngine.score(
        prospect,
        evidence,
    )

    return QualifiedProspectIntelligence(
        scored_prospect=scored,
        business_id="business-1",
        events=[event],
        evidence=evidence,
        intent=intent,
    )


def test_persist_qualified_intelligence():
    client = FakeClient()

    result = persist_qualified_intelligence(
        client,
        [intelligence_item()],
    )

    assert len(result) == 1
    assert result[0].lead_id == "lead-1"

    assert [
        call["name"]
        for call in client.calls
    ] == [
        "ingest_vibe_discovered_leads",
        "persist_vibe_discovery_intelligence",
    ]


def test_empty_input_skips_database():
    client = FakeClient()

    result = persist_qualified_intelligence(
        client,
        [],
    )

    assert result == []
    assert client.calls == []


@pytest.mark.parametrize(
    ("prospect", "stored"),
    [
        (
            {"linkedin_url": "https://linkedin.com/in/jane/"},
            {"linkedin_url": "https://linkedin.com/in/JANE"},
        ),
        (
            {"company_website": "https://example.com/", "person_name": "Jane"},
            {"company_url": "https://EXAMPLE.com", "person_name": "JANE"},
        ),
        ({"vibe_prospect_id": "PROSPECT-1"}, {"vibe_prospect_id": "prospect-1"}),
        ({"vibe_business_id": "BUSINESS-1", "person_name": "Jane"}, {"vibe_business_id": "business-1", "person_name": "Jane"}),
    ],
)
def test_all_supported_provider_identities_match_duplicates(prospect, stored):
    row = {"lead_id": "lead-1", **stored}
    assert _match_stored_lead(prospect, [row]) == row


def test_draft_generation_is_blocked_without_grounded_evidence():
    client = FakeClient()
    item = intelligence_item()
    item = replace(
        item,
        evidence=[],
        intent=IntentEngine.score(item.scored_prospect.prospect, []),
    )

    result = persist_discovery_intelligence(client, [item])

    assert result.draft_count == 0
    assert "create_automatic_vibe_outreach_draft" not in {
        call["name"] for call in client.calls
    }


def test_qualified_grounded_lead_receives_unsent_draft_only():
    client = FakeClient()

    result = persist_discovery_intelligence(client, [intelligence_item()])

    assert result.draft_count == 1
    draft_call = next(
        call for call in client.calls
        if call["name"] == "create_automatic_vibe_outreach_draft"
    )
    assert draft_call["payload"]["draft_evidence_ids"] == ["evidence-1"]
    assert all("send" not in call["name"] for call in client.calls)


def test_vibe_migration_is_additive_indexed_and_non_destructive():
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260907210000_complete_vibe_daily_capture.sql"
    ).read_text()
    lowered = migration.casefold()

    for column in (
        "vibe_prospect_id",
        "vibe_business_id",
        "lead_source",
        "archived_at",
        "archive_reason",
    ):
        assert f"add column if not exists {column}" in lowered

    for index in (
        "leads_vibe_prospect_id_unique",
        "leads_vibe_business_id_unique",
        "leads_company_url_lookup_idx",
        "leads_archive_retention_idx",
    ):
        assert f"create" in lowered and index in lowered

    assert "delete from public.leads" not in lowered
    assert "drop table" not in lowered
    assert "non-destructive retention marker" in lowered
    assert "6-12 months" in lowered


def test_scored_bad_fits_are_retained_and_qualified_leads_enter_review():
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260904214500_persist_vibe_discovery_intelligence.sql"
    ).read_text().casefold()

    assert "computed_status := 'disqualified'" in migration
    assert "computed_status := 'nurture'" in migration
    assert "computed_status := 'review'" in migration
    assert "update public.leads" in migration
    assert "delete from public.leads" not in migration


def test_service_only_functions_fail_closed_and_revoke_public_execution():
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260907210000_complete_vibe_daily_capture.sql"
    ).read_text().casefold()

    assert "coalesce(current_setting('request.jwt.claim.role', true), '')" in migration
    assert "from public, anon, authenticated" in migration
    assert "to service_role" in migration
