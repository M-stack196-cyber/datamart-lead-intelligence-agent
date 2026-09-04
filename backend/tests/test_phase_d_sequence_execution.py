from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.services import outreach_generation
from app.services.outreach_delivery import (
    approve_outreach_message,
    send_outreach_message,
)
from app.services.outreach_generation import (
    generate_outreach_message,
    reset_fallback_outreach_state,
)
from app.services.sequence_execution import (
    get_sequence_state,
    pause_sequence,
    resume_sequence,
    run_due_followups,
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


def send_first_step(
    settings: Settings,
    *,
    lead_id: str = "lead-01",
) -> dict:
    generate_outreach_message(
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

    return send_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
    )


def start_sequence(
    settings: Settings,
    *,
    lead_id: str = "lead-01",
) -> dict:
    send_first_step(
        settings,
        lead_id=lead_id,
    )

    return schedule_next_followup(
        settings,
        "user-1",
        "admin",
        lead_id,
    )


def test_first_send_schedules_step_two(
    settings: Settings,
) -> None:
    result = start_sequence(settings)

    assert result["status"] == "scheduled"
    assert result["current_step_number"] == 2
    assert result["next_run_at"]
    assert result["idempotent"] is False

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["status"] == "scheduled"
    assert state["current_step_number"] == 2
    assert state["total_steps"] == 4
    assert len(state["messages"]) == 2

    step_one = state["messages"][0]
    step_two = state["messages"][1]

    assert step_one["step_number"] == 1
    assert step_one["status"] == "sent"

    assert step_two["step_number"] == 2
    assert step_two["status"] == "scheduled"
    assert step_two["scheduled_at"]


def test_step_two_is_scheduled_three_days_after_step_one(
    settings: Settings,
) -> None:
    first = send_first_step(settings)

    sent_at = datetime.fromisoformat(
        first["sent_at"].replace("Z", "+00:00")
    )

    result = schedule_next_followup(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    scheduled_at = datetime.fromisoformat(
        result["next_run_at"].replace("Z", "+00:00")
    )

    assert scheduled_at == sent_at + timedelta(days=3)


def test_scheduling_same_followup_is_idempotent(
    settings: Settings,
) -> None:
    send_first_step(settings)

    first = schedule_next_followup(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    second = schedule_next_followup(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert first["status"] == "scheduled"
    assert second["status"] == "scheduled"
    assert second["idempotent"] is True
    assert second["message_id"] == first["message_id"]
    assert second["next_run_at"] == first["next_run_at"]

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert len(state["messages"]) == 2


def test_due_runner_does_not_send_before_due_time(
    settings: Settings,
) -> None:
    result = start_sequence(settings)

    next_run_at = datetime.fromisoformat(
        result["next_run_at"].replace("Z", "+00:00")
    )

    runner = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=next_run_at - timedelta(seconds=1),
    )

    assert runner["processed"] == 0

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["messages"][-1]["step_number"] == 2
    assert state["messages"][-1]["status"] == "scheduled"


def test_due_runner_sends_followup_and_schedules_next_step(
    settings: Settings,
) -> None:
    result = start_sequence(settings)

    next_run_at = datetime.fromisoformat(
        result["next_run_at"].replace("Z", "+00:00")
    )

    runner = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=next_run_at + timedelta(seconds=1),
    )

    assert runner["processed"] == 1
    assert runner["results"][0]["status"] == "sent"
    assert runner["results"][0]["step_number"] == 2

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["status"] == "scheduled"
    assert state["current_step_number"] == 3
    assert len(state["messages"]) == 3

    step_two = state["messages"][1]
    step_three = state["messages"][2]

    assert step_two["status"] == "sent"
    assert step_two["provider_message_id"]

    assert step_three["step_number"] == 3
    assert step_three["status"] == "scheduled"


def test_manager_can_pause_and_resume_sequence(
    settings: Settings,
) -> None:
    start_sequence(settings)

    paused = pause_sequence(
        settings,
        "manager-1",
        "manager",
        "lead-01",
        reason="Waiting for internal review",
    )

    assert paused["status"] == "paused"
    assert (
        paused["paused_reason"]
        == "Waiting for internal review"
    )

    state = get_sequence_state(
        settings,
        "manager-1",
        "manager",
        "lead-01",
    )

    assert state["status"] == "paused"
    assert (
        state["paused_reason"]
        == "Waiting for internal review"
    )

    resumed = resume_sequence(
        settings,
        "manager-1",
        "manager",
        "lead-01",
    )

    assert resumed["status"] == "scheduled"
    assert resumed["next_run_at"]

    state = get_sequence_state(
        settings,
        "manager-1",
        "manager",
        "lead-01",
    )

    assert state["status"] == "scheduled"
    assert state["paused_reason"] is None


def test_sales_user_cannot_pause_sequence(
    settings: Settings,
) -> None:
    start_sequence(settings)

    with pytest.raises(
        PermissionError,
        match="Admin or manager role required",
    ):
        pause_sequence(
            settings,
            "user-1",
            "sales",
            "lead-01",
            reason="Sales pause",
        )


def test_suppression_blocks_automatic_followup(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = start_sequence(settings)

    next_run_at = datetime.fromisoformat(
        result["next_run_at"].replace("Z", "+00:00")
    )

    monkeypatch.setitem(
        outreach_generation._FALLBACK_LEADS["lead-01"],
        "email",
        "suppressed@datamart.test",
    )

    runner = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=next_run_at + timedelta(seconds=1),
    )

    assert runner["processed"] == 1
    assert runner["results"][0]["status"] == "paused"
    assert "suppressed" in runner["results"][0]["reason"].lower()

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["status"] == "paused"
    assert "suppressed" in (
        state["paused_reason"] or ""
    ).lower()

    assert state["messages"][-1]["status"] == "scheduled"


def test_disqualified_lead_blocks_automatic_followup(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = start_sequence(settings)

    next_run_at = datetime.fromisoformat(
        result["next_run_at"].replace("Z", "+00:00")
    )

    monkeypatch.setitem(
        outreach_generation._FALLBACK_LEADS["lead-01"],
        "status",
        "disqualified",
    )

    runner = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=next_run_at + timedelta(seconds=1),
    )

    assert runner["processed"] == 1
    assert runner["results"][0]["status"] == "paused"
    assert "disqualified" in (
        runner["results"][0]["reason"]
    ).lower()


def test_sequence_completes_after_final_step(
    settings: Settings,
) -> None:
    start_sequence(settings)

    future = (
        datetime.now(tz=UTC)
        + timedelta(days=60)
    )

    second = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=future,
    )

    assert second["processed"] == 1
    assert second["results"][0]["step_number"] == 2

    third = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=future,
    )

    assert third["processed"] == 1
    assert third["results"][0]["step_number"] == 3

    fourth = run_due_followups(
        settings,
        "user-1",
        "admin",
        now=future,
    )

    assert fourth["processed"] == 1
    assert fourth["results"][0]["step_number"] == 4

    state = get_sequence_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert state["status"] == "completed"
    assert state["current_step_number"] == 4
    assert state["next_run_at"] is None
    assert len(state["messages"]) == 4

    assert all(
        message["status"] == "sent"
        for message in state["messages"]
    )


def test_sequence_events_are_recorded(
    settings: Settings,
) -> None:
    result = start_sequence(settings)

    next_run_at = datetime.fromisoformat(
        result["next_run_at"].replace("Z", "+00:00")
    )

    run_due_followups(
        settings,
        "user-1",
        "admin",
        now=next_run_at + timedelta(seconds=1),
    )

    raw_state = (
        outreach_generation
        ._FALLBACK_STATE["lead-01"]
    )

    event_types = {
        event["event_type"]
        for event in raw_state["events"]
    }

    assert "outreach_sent" in event_types
    assert "followup_scheduled" in event_types
    assert "followup_send_attempted" in event_types
    assert "followup_sent" in event_types


def test_only_manager_roles_can_run_due_followups(
    settings: Settings,
) -> None:
    start_sequence(settings)

    with pytest.raises(
        PermissionError,
        match="Admin or manager role required",
    ):
        run_due_followups(
            settings,
            "user-1",
            "sales",
            now=datetime.now(tz=UTC)
            + timedelta(days=60),
        )
