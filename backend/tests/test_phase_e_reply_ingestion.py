from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.integrations.outbound import InboundReplyRequest
from app.services import outreach_generation
from app.services.outreach_delivery import (
    approve_outreach_message,
    send_outreach_message,
)
from app.services.outreach_generation import (
    generate_outreach_message,
    reset_fallback_outreach_state,
)
from app.services.reply_ingestion import (
    classify_reply,
    ingest_inbound_reply,
    list_inbound_replies,
)
from app.services.sequence_execution import (
    get_sequence_state,
    schedule_next_followup,
)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_fallback_outreach_state()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="development",
        outbound_email_provider="mock",
        supabase_url=None,
        supabase_service_role_key=None,
        gmail_sender_email="outreach@datamart.test",
        aws_bearer_token_bedrock=None,
        bedrock_model_id=None,
    )


def start_sequence(
    settings: Settings,
    *,
    lead_id: str = "lead-01",
) -> dict:
    generated = generate_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
        channel="email",
    )

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
    )

    send_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
    )

    schedule_next_followup(
        settings,
        "user-1",
        "admin",
        lead_id,
    )

    return generated


def make_reply(
    settings: Settings,
    *,
    body: str = "I'm interested. Happy to discuss.",
    subject: str = "Re: quick question",
    provider_message_id: str = "provider-reply-001",
    actor_id: str = "user-1",
    role: str = "admin",
) -> dict:
    generated = start_sequence(settings)

    request = InboundReplyRequest(
        provider_name="mock",
        lead_id="lead-01",
        lead_outreach_id=generated["lead_outreach_id"],
        thread_id="thread-001",
        provider_message_id=provider_message_id,
        from_email="lead-01@datamart.test",
        to_email="outreach@datamart.test",
        subject=subject,
        body=body,
        received_at=datetime.now(tz=UTC),
        metadata={"source": "test"},
    )

    return ingest_inbound_reply(
        settings,
        actor_id,
        role,
        request,
    )


def test_classifies_interested_reply() -> None:
    classification, reason, unsubscribe = classify_reply(
        "Re: hello",
        "I'm interested. Tell me more.",
    )

    assert classification.value == "interested"
    assert reason
    assert unsubscribe is False


def test_classifies_meeting_request() -> None:
    classification, reason, unsubscribe = classify_reply(
        "Re: hello",
        "Can we schedule a call next week?",
    )

    assert classification.value == "meeting_request"
    assert reason
    assert unsubscribe is False


def test_classifies_question_reply() -> None:
    classification, reason, unsubscribe = classify_reply(
        "Re: hello",
        "What does your implementation process look like?",
    )

    assert classification.value == "question"
    assert reason
    assert unsubscribe is False


def test_classifies_unsubscribe_reply() -> None:
    classification, reason, unsubscribe = classify_reply(
        "Re: hello",
        "Please unsubscribe me.",
    )

    assert classification.value == "unsubscribe"
    assert reason
    assert unsubscribe is True


def test_reply_marks_sequence_replied(
    settings: Settings,
) -> None:
    result = make_reply(settings)

    assert result["classification"] == "interested"
    assert result["idempotent"] is False

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["status"] == "replied"


def test_reply_stops_scheduled_followup(
    settings: Settings,
) -> None:
    make_reply(settings)

    raw_state = outreach_generation._FALLBACK_STATE[
        "lead-01"
    ]

    outbound_messages = [
        item
        for item in raw_state["messages"]
        if item.get("direction") == "outbound"
    ]

    assert len(outbound_messages) == 2
    assert outbound_messages[0]["status"] == "sent"
    assert outbound_messages[1]["status"] == "paused"


def test_reply_persists_inbound_message(
    settings: Settings,
) -> None:
    result = make_reply(settings)

    raw_state = outreach_generation._FALLBACK_STATE[
        "lead-01"
    ]

    inbound_messages = [
        item
        for item in raw_state["messages"]
        if item.get("direction") == "inbound"
    ]

    assert len(inbound_messages) == 1

    inbound = inbound_messages[0]

    assert inbound["status"] == "replied"
    assert inbound["body"] == "I'm interested. Happy to discuss."
    assert inbound["provider_message_id"] == "provider-reply-001"
    assert result["outreach_message_id"] == inbound["id"]


def test_duplicate_reply_is_idempotent(
    settings: Settings,
) -> None:
    generated = start_sequence(settings)

    received_at = datetime.now(tz=UTC)

    request = InboundReplyRequest(
        provider_name="mock",
        lead_id="lead-01",
        lead_outreach_id=generated["lead_outreach_id"],
        thread_id="thread-001",
        provider_message_id="duplicate-provider-message",
        from_email="lead-01@datamart.test",
        to_email="outreach@datamart.test",
        subject="Re: hello",
        body="I'm interested.",
        received_at=received_at,
        metadata={},
    )

    first = ingest_inbound_reply(
        settings,
        "user-1",
        "admin",
        request,
    )

    second = ingest_inbound_reply(
        settings,
        "user-1",
        "admin",
        request,
    )

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert first["id"] == second["id"]

    raw_state = outreach_generation._FALLBACK_STATE[
        "lead-01"
    ]

    assert len(raw_state["inbound_replies"]) == 1

    inbound_messages = [
        item
        for item in raw_state["messages"]
        if item.get("direction") == "inbound"
    ]

    assert len(inbound_messages) == 1


def test_unsubscribe_adds_suppression(
    settings: Settings,
) -> None:
    result = make_reply(
        settings,
        body="Please unsubscribe me from future emails.",
        provider_message_id="unsubscribe-reply-001",
    )

    assert result["classification"] == "unsubscribe"
    assert result["is_unsubscribe"] is True

    raw_state = outreach_generation._FALLBACK_STATE[
        "lead-01"
    ]

    assert (
        "lead-01@datamart.test"
        in raw_state["suppression_emails"]
    )

    event_types = {
        item["event_type"]
        for item in raw_state["events"]
    }

    assert "suppression_added" in event_types


def test_assigned_sales_user_can_ingest_reply(
    settings: Settings,
) -> None:
    generated = start_sequence(settings)

    request = InboundReplyRequest(
        provider_name="mock",
        lead_id="lead-01",
        lead_outreach_id=generated["lead_outreach_id"],
        thread_id="thread-sales",
        provider_message_id="sales-reply-001",
        from_email="lead-01@datamart.test",
        to_email="outreach@datamart.test",
        subject="Re: hello",
        body="What is the implementation timeline?",
        received_at=datetime.now(tz=UTC),
        metadata={},
    )

    result = ingest_inbound_reply(
        settings,
        "user-1",
        "sales",
        request,
    )

    assert result["classification"] == "question"


def test_unassigned_sales_user_cannot_ingest_reply(
    settings: Settings,
) -> None:
    generated = start_sequence(settings)

    request = InboundReplyRequest(
        provider_name="mock",
        lead_id="lead-01",
        lead_outreach_id=generated["lead_outreach_id"],
        thread_id="thread-sales-blocked",
        provider_message_id="sales-reply-blocked",
        from_email="lead-01@datamart.test",
        to_email="outreach@datamart.test",
        subject="Re: hello",
        body="Hello",
        received_at=datetime.now(tz=UTC),
        metadata={},
    )

    with pytest.raises(
        PermissionError,
        match="not assigned",
    ):
        ingest_inbound_reply(
            settings,
            "different-sales-user",
            "sales",
            request,
        )


def test_list_inbound_replies(
    settings: Settings,
) -> None:
    make_reply(settings)

    replies = list_inbound_replies(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert len(replies) == 1
    assert replies[0]["classification"] == "interested"
    assert replies[0]["from_email"] == "lead-01@datamart.test"


def test_reply_events_are_recorded(
    settings: Settings,
) -> None:
    make_reply(settings)

    raw_state = outreach_generation._FALLBACK_STATE[
        "lead-01"
    ]

    event_types = {
        item["event_type"]
        for item in raw_state["events"]
    }

    assert "reply_received" in event_types
    assert "reply_classified" in event_types
    assert "sequence_stopped_for_reply" in event_types
