from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.services import outreach_delivery, outreach_generation
from app.services.outreach_analytics import (
    _metrics_from_timeline,
    get_lead_outreach_analytics,
    get_lead_outreach_timeline,
)


def offline_settings(**overrides) -> Settings:
    values = {
        "supabase_url": None,
        "supabase_service_role_key": None,
        "aws_bearer_token_bedrock": None,
        "bedrock_model_id": None,
        **overrides,
    }

    return Settings(
        _env_file=None,
        **values,
    )


@pytest.fixture(autouse=True)
def reset_fallback_state():
    outreach_generation._FALLBACK_STATE.clear()
    outreach_generation._FALLBACK_LEADS.clear()

    yield

    outreach_generation._FALLBACK_STATE.clear()
    outreach_generation._FALLBACK_LEADS.clear()


def seed_lead(
    *,
    lead_id: str = "phase-g-lead",
    assigned_sales_rep_id: str | None = "sales-1",
):
    now = datetime.now(tz=UTC)

    outreach_generation._FALLBACK_LEADS[lead_id] = {
        "id": lead_id,
        "name": "Phase G Lead",
        "email": "phase-g@example.com",
        "status": "qualified",
        "assigned_to": assigned_sales_rep_id,
    }

    outreach_generation._FALLBACK_STATE[lead_id] = {
        "lead_outreach": {
            "id": "outreach-phase-g",
            "lead_id": lead_id,
        },
        "latest_message": {
            "id": "message-phase-g",
            "lead_outreach_id": "outreach-phase-g",
            "direction": "outbound",
            "status": "sent",
            "subject": "Phase G test",
            "body": "Test message",
            "sent_at": (
                now - timedelta(minutes=20)
            ).isoformat(),
        },
        "messages": [],
        "events": [
            {
                "id": "event-generated",
                "event_type": "outreach_generated",
                "event_payload": {},
                "occurred_at": (
                    now - timedelta(minutes=30)
                ).isoformat(),
            },
            {
                "id": "event-sent",
                "event_type": "outreach_sent",
                "event_payload": {},
                "occurred_at": (
                    now - timedelta(minutes=20)
                ).isoformat(),
            },
        ],
        "inbound_reply_events": [
            {
                "id": "reply-1",
                "lead_id": lead_id,
                "lead_outreach_id": "outreach-phase-g",
                "classification": "interested",
                "is_unsubscribe": False,
                "from_email": "phase-g@example.com",
                "subject": "Re: Hello",
                "received_at": (
                    now - timedelta(minutes=10)
                ).isoformat(),
            }
        ],
        "crm_sync_states": {
            "mock": {
                "id": "crm-1",
                "lead_id": lead_id,
                "lead_outreach_id": "outreach-phase-g",
                "provider_key": "mock",
                "external_crm_id": "mock-crm-1",
                "sync_status": "synced",
                "error_message": None,
                "synced_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "created_at": (
                    now - timedelta(minutes=5)
                ).isoformat(),
            }
        },
    }

    return lead_id


def test_timeline_contains_outreach_reply_and_crm():
    settings = offline_settings()
    lead_id = seed_lead()

    timeline = get_lead_outreach_timeline(
        settings,
        "admin-1",
        "admin",
        lead_id,
    )

    sources = {
        item["source"]
        for item in timeline
    }

    assert "outreach_event" in sources
    assert "inbound_reply" in sources
    assert "crm_state" in sources


def test_timeline_is_reverse_chronological():
    settings = offline_settings()
    lead_id = seed_lead()

    timeline = get_lead_outreach_timeline(
        settings,
        "admin-1",
        "admin",
        lead_id,
    )

    timestamps = [
        item["occurred_at"]
        for item in timeline
        if item["occurred_at"]
    ]

    parsed = [
        datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
        for value in timestamps
    ]

    assert parsed == sorted(
        parsed,
        reverse=True,
    )


def test_admin_can_view_any_lead():
    settings = offline_settings()
    lead_id = seed_lead(
        assigned_sales_rep_id="sales-other",
    )

    timeline = get_lead_outreach_timeline(
        settings,
        "admin-1",
        "admin",
        lead_id,
    )

    assert timeline


def test_manager_can_view_any_lead():
    settings = offline_settings()
    lead_id = seed_lead(
        assigned_sales_rep_id="sales-other",
    )

    timeline = get_lead_outreach_timeline(
        settings,
        "manager-1",
        "manager",
        lead_id,
    )

    assert timeline


def test_assigned_sales_can_view_lead():
    settings = offline_settings()
    lead_id = seed_lead(
        assigned_sales_rep_id="sales-1",
    )

    timeline = get_lead_outreach_timeline(
        settings,
        "sales-1",
        "sales",
        lead_id,
    )

    assert timeline


def test_unassigned_sales_cannot_view_lead():
    settings = offline_settings()
    lead_id = seed_lead(
        assigned_sales_rep_id="sales-2",
    )

    with pytest.raises(PermissionError):
        get_lead_outreach_timeline(
            settings,
            "sales-1",
            "sales",
            lead_id,
        )


def test_missing_lead_raises_value_error():
    settings = offline_settings()

    with pytest.raises(ValueError):
        get_lead_outreach_timeline(
            settings,
            "admin-1",
            "admin",
            "missing-lead",
        )


def test_metrics_count_sent_reply_and_crm():
    timeline = [
        {
            "event_type": "outreach_sent",
            "source": "outreach_event",
            "payload": {},
        },
        {
            "event_type": "followup_sent",
            "source": "outreach_event",
            "payload": {},
        },
        {
            "event_type": "reply_received",
            "source": "inbound_reply",
            "payload": {
                "classification": "interested",
                "is_unsubscribe": False,
            },
        },
        {
            "event_type": "crm_state_synced",
            "source": "crm_state",
            "payload": {},
        },
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert metrics["sent_count"] == 2
    assert metrics["reply_count"] == 1
    assert metrics["reply_rate"] == 0.5
    assert metrics["interested_count"] == 1
    assert metrics["crm_synced_count"] == 1


def test_metrics_count_meeting_requests():
    timeline = [
        {
            "event_type": "reply_received",
            "source": "inbound_reply",
            "payload": {
                "classification": "meeting_request",
                "is_unsubscribe": False,
            },
        }
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert (
        metrics["meeting_request_count"]
        == 1
    )


def test_metrics_count_not_interested():
    timeline = [
        {
            "event_type": "reply_received",
            "source": "inbound_reply",
            "payload": {
                "classification": "not_interested",
                "is_unsubscribe": False,
            },
        }
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert (
        metrics["not_interested_count"]
        == 1
    )


def test_metrics_count_unsubscribe():
    timeline = [
        {
            "event_type": "reply_received",
            "source": "inbound_reply",
            "payload": {
                "classification": "unsubscribe",
                "is_unsubscribe": True,
            },
        }
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert metrics["unsubscribe_count"] == 1


def test_metrics_count_crm_failure():
    timeline = [
        {
            "event_type": "crm_state_failed",
            "source": "crm_state",
            "payload": {},
        }
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert metrics["crm_failed_count"] == 1


def test_reply_rate_zero_when_no_sent_messages():
    timeline = [
        {
            "event_type": "reply_received",
            "source": "inbound_reply",
            "payload": {
                "classification": "question",
                "is_unsubscribe": False,
            },
        }
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert metrics["sent_count"] == 0
    assert metrics["reply_count"] == 1
    assert metrics["reply_rate"] == 0.0


def test_analytics_returns_lead_summary():
    settings = offline_settings()
    lead_id = seed_lead()

    result = get_lead_outreach_analytics(
        settings,
        "admin-1",
        "admin",
        lead_id,
    )

    assert result["lead_id"] == lead_id
    assert result["timeline_count"] == 4

    metrics = result["metrics"]

    assert metrics["sent_count"] == 1
    assert metrics["reply_count"] == 1
    assert metrics["reply_rate"] == 1.0
    assert metrics["interested_count"] == 1
    assert metrics["crm_synced_count"] == 1


def test_unknown_events_are_preserved():
    timeline = [
        {
            "event_type": "future_custom_event",
            "source": "outreach_event",
            "payload": {},
        }
    ]

    metrics = _metrics_from_timeline(
        timeline
    )

    assert (
        metrics["event_counts"][
            "future_custom_event"
        ]
        == 1
    )
