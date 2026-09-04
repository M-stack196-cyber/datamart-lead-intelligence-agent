from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.integrations.outbound import (
    CrmHandoffRequest,
    CrmHandoffResult,
)
from app.services import outreach_generation
from app.services.crm_handoff import (
    get_crm_sync_state,
    push_lead_to_crm,
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


class RecordingCrmProvider:
    def __init__(self) -> None:
        self.requests: list[CrmHandoffRequest] = []

    def push(
        self,
        request: CrmHandoffRequest,
    ) -> CrmHandoffResult:
        self.requests.append(request)

        return CrmHandoffResult(
            provider_key=request.provider_key,
            external_crm_id="crm-contact-123",
            sync_status="synced",
            synced_at=datetime.now(tz=UTC),
            raw_response={"ok": True},
        )


class FailingCrmProvider:
    def __init__(self) -> None:
        self.requests: list[CrmHandoffRequest] = []

    def push(
        self,
        request: CrmHandoffRequest,
    ) -> CrmHandoffResult:
        self.requests.append(request)
        raise RuntimeError("CRM provider unavailable")


@pytest.fixture(autouse=True)
def reset_state() -> None:
    outreach_generation.reset_fallback_outreach_state()


@pytest.fixture
def settings() -> Settings:
    return offline_settings()


def _prepare_lead() -> None:
    from app.services.outreach_generation import (
        generate_outreach_message,
    )

    generate_outreach_message(
        offline_settings(),
        "user-1",
        "admin",
        "lead-01",
    )


def test_admin_can_push_lead_to_crm(
    settings: Settings,
) -> None:
    _prepare_lead()

    provider = RecordingCrmProvider()

    result = push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {
            "name": "Lead name",
            "email": "lead-01@datamart.test",
        },
        provider=provider,
    )

    assert result["sync_status"] == "synced"
    assert result["external_crm_id"] == "crm-contact-123"
    assert result["provider_key"] == "mock"
    assert result["idempotent"] is False
    assert len(provider.requests) == 1


def test_manager_can_push_lead_to_crm(
    settings: Settings,
) -> None:
    _prepare_lead()

    provider = RecordingCrmProvider()

    result = push_lead_to_crm(
        settings,
        "manager-1",
        "manager",
        "lead-01",
        "mock",
        {},
        provider=provider,
    )

    assert result["sync_status"] == "synced"


def test_sales_cannot_manage_crm_sync(
    settings: Settings,
) -> None:
    _prepare_lead()

    with pytest.raises(
        PermissionError,
        match="Manager or admin role required",
    ):
        push_lead_to_crm(
            settings,
            "user-1",
            "sales",
            "lead-01",
            "mock",
            {},
            provider=RecordingCrmProvider(),
        )


def test_second_sync_is_idempotent(
    settings: Settings,
) -> None:
    _prepare_lead()

    provider = RecordingCrmProvider()

    first = push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=provider,
    )

    second = push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=provider,
    )

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert len(provider.requests) == 1


def test_idempotency_key_is_stable(
    settings: Settings,
) -> None:
    _prepare_lead()

    provider = RecordingCrmProvider()

    push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=provider,
    )

    request = provider.requests[0]

    assert request.idempotency_key.startswith("crm-")
    assert request.lead_id == "lead-01"
    assert request.provider_key == "mock"


def test_provider_failure_is_persisted(
    settings: Settings,
) -> None:
    _prepare_lead()

    result = push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=FailingCrmProvider(),
    )

    assert result["sync_status"] == "failed"
    assert result["error_message"] == (
        "CRM provider unavailable"
    )
    assert result["next_sync_at"] is not None


def test_failed_sync_can_be_retried(
    settings: Settings,
) -> None:
    _prepare_lead()

    push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=FailingCrmProvider(),
    )

    provider = RecordingCrmProvider()

    result = push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=provider,
    )

    assert result["sync_status"] == "synced"
    assert result["error_message"] is None
    assert len(provider.requests) == 1


def test_mapping_is_persisted(
    settings: Settings,
) -> None:
    _prepare_lead()

    mapping = {
        "email": "lead-01@datamart.test",
        "source": "datamart",
    }

    result = push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        mapping,
        provider=RecordingCrmProvider(),
    )

    assert result["mapping"] == mapping


def test_get_crm_sync_state(
    settings: Settings,
) -> None:
    _prepare_lead()

    push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=RecordingCrmProvider(),
    )

    rows = get_crm_sync_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
    )

    assert len(rows) == 1
    assert rows[0]["provider_key"] == "mock"
    assert rows[0]["sync_status"] == "synced"


def test_get_crm_state_can_filter_provider(
    settings: Settings,
) -> None:
    _prepare_lead()

    push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=RecordingCrmProvider(),
    )

    rows = get_crm_sync_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
        provider_key="mock",
    )

    assert len(rows) == 1

    missing = get_crm_sync_state(
        settings,
        "user-1",
        "admin",
        "lead-01",
        provider_key="other",
    )

    assert missing == []


def test_sync_events_are_recorded(
    settings: Settings,
) -> None:
    _prepare_lead()

    push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=RecordingCrmProvider(),
    )

    raw_state = (
        outreach_generation._FALLBACK_STATE[
            "lead-01"
        ]
    )

    event_types = [
        event["event_type"]
        for event in raw_state.get("events", [])
    ]

    assert "crm_sync_started" in event_types
    assert "crm_sync_succeeded" in event_types


def test_failed_sync_event_is_recorded(
    settings: Settings,
) -> None:
    _prepare_lead()

    push_lead_to_crm(
        settings,
        "user-1",
        "admin",
        "lead-01",
        "mock",
        {},
        provider=FailingCrmProvider(),
    )

    raw_state = (
        outreach_generation._FALLBACK_STATE[
            "lead-01"
        ]
    )

    event_types = [
        event["event_type"]
        for event in raw_state.get("events", [])
    ]

    assert "crm_sync_failed" in event_types


def test_empty_provider_key_is_rejected(
    settings: Settings,
) -> None:
    _prepare_lead()

    with pytest.raises(
        ValueError,
        match="CRM provider key is required",
    ):
        push_lead_to_crm(
            settings,
            "user-1",
            "admin",
            "lead-01",
            "   ",
            {},
        )
