from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.outreach_delivery import (
    approve_outreach_message,
    send_outreach_message,
)
from app.services.outreach_generation import (
    generate_outreach_message,
    get_outreach_state,
    reset_fallback_outreach_state,
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


def create_draft(settings: Settings, lead_id: str = "lead-01") -> dict:
    return generate_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
        channel="email",
    )


def test_draft_cannot_be_sent_before_explicit_approval(
    settings: Settings,
) -> None:
    create_draft(settings)

    with pytest.raises(
        ValueError,
        match="Draft must be approved before sending",
    ):
        send_outreach_message(
            settings,
            "user-1",
            "admin",
            "lead-01",
        )


def test_only_admin_can_approve_outreach(
    settings: Settings,
) -> None:
    create_draft(settings)

    with pytest.raises(
        PermissionError,
        match="Admin role required for outreach approval",
    ):
        approve_outreach_message(
            settings,
            "user-1",
            "manager",
            "lead-01",
        )


def test_admin_can_approve_draft(
    settings: Settings,
) -> None:
    create_draft(settings)

    result = approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert result["status"] == "approved"
    assert result["approved_by"] == "user-1"
    assert result["approved_at"]
    assert result["idempotent"] is False

    state = get_outreach_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["latest_message"]["status"] == "approved"
    assert state["lead_outreach"]["status"] == "approved"


def test_approval_is_idempotent(
    settings: Settings,
) -> None:
    create_draft(settings)

    first = approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    second = approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert first["status"] == "approved"
    assert second["status"] == "approved"
    assert second["idempotent"] is True
    assert second["approved_at"] == first["approved_at"]


def test_approved_draft_can_be_sent(
    settings: Settings,
) -> None:
    create_draft(settings)

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    result = send_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert result["status"] == "sent"
    assert result["provider"] == "mock"
    assert result["provider_message_id"].startswith("mock-email-")
    assert result["sent_at"]
    assert result["idempotent"] is False

    state = get_outreach_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["latest_message"]["status"] == "sent"
    assert state["lead_outreach"]["status"] == "sent"
    assert state["latest_message"]["provider_message_id"]
    assert state["latest_message"]["sent_at"]


def test_repeated_send_is_idempotent(
    settings: Settings,
) -> None:
    create_draft(settings)

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    first = send_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    second = send_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert first["status"] == "sent"
    assert first["idempotent"] is False

    assert second["status"] == "sent"
    assert second["idempotent"] is True

    assert (
        second["provider_message_id"]
        == first["provider_message_id"]
    )


def test_suppressed_recipient_cannot_be_approved(
    settings: Settings,
) -> None:
    with pytest.raises(
        PermissionError,
        match="suppressed",
    ):
        generate_outreach_message(
            settings,
            "user-1",
            "admin",
            "lead-04",
            channel="email",
        )


def test_disqualified_lead_cannot_receive_outreach(
    settings: Settings,
) -> None:
    with pytest.raises(
        ValueError,
        match="disqualified",
    ):
        generate_outreach_message(
            settings,
            "user-1",
            "admin",
            "lead-03",
            channel="email",
        )


def test_sales_user_can_send_assigned_approved_message(
    settings: Settings,
) -> None:
    create_draft(settings)

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    result = send_outreach_message(
        settings,
        "user-1",
        "sales",
        "lead-01",
    )

    assert result["status"] == "sent"


def test_unassigned_sales_user_cannot_send(
    settings: Settings,
) -> None:
    create_draft(settings)

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    with pytest.raises(
        PermissionError,
        match="not assigned",
    ):
        send_outreach_message(
            settings,
            "another-sales-user",
            "sales",
            "lead-01",
        )


def test_sent_message_cannot_be_approved_again(
    settings: Settings,
) -> None:
    create_draft(settings)

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    send_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    with pytest.raises(
        ValueError,
        match="Sent messages cannot be approved again",
    ):
        approve_outreach_message(
            settings,
            "user-1",
            "admin",
            "lead-01",
        )


def test_delivery_events_are_recorded(
    settings: Settings,
) -> None:
    create_draft(settings)

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    send_outreach_message(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    state = get_outreach_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    event_types = {
        event["event_type"]
        for event in state["events"]
    }

    assert "outreach_generated" in event_types
    assert "outreach_approved" in event_types
    assert "outreach_send_attempted" in event_types
    assert "outreach_sent" in event_types
