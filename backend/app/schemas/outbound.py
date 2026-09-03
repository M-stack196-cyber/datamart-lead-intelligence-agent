from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutboundLifecycleStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    SENT = "sent"
    REPLIED = "replied"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class OutboundDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class SuppressionKind(StrEnum):
    UNSUBSCRIBED = "unsubscribed"
    MANUAL = "manual"
    PERMANENT = "permanent"


class CrmSyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    SKIPPED = "skipped"


class OutreachSequenceStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    sequence_id: str
    step_number: int = Field(ge=1)
    delay_days: int = Field(ge=0)
    subject_template: str
    message_template: str
    is_enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_templates(self) -> "OutreachSequenceStep":
        if not self.subject_template.strip():
            raise ValueError("subject_template is required")
        if not self.message_template.strip():
            raise ValueError("message_template is required")
        return self


class OutreachSequence(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    external_id: str
    name: str
    description: str | None = None
    channel: Literal["email"] = "email"
    is_enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    steps: list[OutreachSequenceStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def sort_and_validate_steps(self) -> "OutreachSequence":
        step_numbers = [step.step_number for step in self.steps]
        if len(step_numbers) != len(set(step_numbers)):
            raise ValueError("sequence step numbers must be unique")
        object.__setattr__(
            self,
            "steps",
            sorted(self.steps, key=lambda step: step.step_number),
        )
        return self


class LeadOutreach(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    lead_id: str
    sequence_id: str
    status: OutboundLifecycleStatus
    current_step_number: int = Field(ge=1)
    next_run_at: str | None = None
    provider_thread_id: str | None = None
    paused_reason: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_pause_state(self) -> "LeadOutreach":
        if (
            self.status == OutboundLifecycleStatus.PAUSED
            and not (self.paused_reason or "").strip()
        ):
            raise ValueError(
                "paused_reason is required when the outreach is paused"
            )
        return self


class OutreachMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    lead_outreach_id: str
    sequence_step_id: str | None = None
    step_number: int | None = Field(default=None, ge=1)
    direction: OutboundDirection = OutboundDirection.OUTBOUND
    status: OutboundLifecycleStatus = OutboundLifecycleStatus.DRAFT
    subject: str | None = None
    body: str
    generation_provider: str = "mock"
    generation_model: str | None = None
    provider_message_id: str | None = None
    idempotency_key: str | None = None
    error_message: str | None = None
    provider_response: dict[str, object] = Field(default_factory=dict)
    generated_at: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    scheduled_at: str | None = None
    sent_at: str | None = None
    replied_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "OutreachMessage":
        if not self.body.strip():
            raise ValueError("body is required")

        if (
            self.status
            in {
                OutboundLifecycleStatus.SCHEDULED,
                OutboundLifecycleStatus.SENT,
            }
            and not (self.idempotency_key or "").strip()
        ):
            raise ValueError(
                "idempotency_key is required for scheduled or sent messages"
            )

        if (
            self.status == OutboundLifecycleStatus.APPROVED
            and not self.approved_at
        ):
            raise ValueError(
                "approved_at is required for approved messages"
            )

        if (
            self.status == OutboundLifecycleStatus.REPLIED
            and self.direction != OutboundDirection.INBOUND
        ):
            raise ValueError("replied messages must be inbound")

        if (
            self.status == OutboundLifecycleStatus.FAILED
            and not (self.error_message or "").strip()
        ):
            raise ValueError(
                "error_message is required for failed messages"
            )

        return self


class OutreachEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    lead_outreach_id: str
    message_id: str | None = None
    event_type: str
    event_payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: str | None = None
    created_by: str | None = None


class SuppressionEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    email: str
    suppression_kind: SuppressionKind
    reason: str | None = None
    source: str = "manual"
    is_active: bool = True
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    normalized_email: str | None = None

    @model_validator(mode="after")
    def normalize_email(self) -> "SuppressionEntry":
        object.__setattr__(
            self,
            "normalized_email",
            (self.email or "").strip().casefold(),
        )
        return self


class CrmSyncMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    lead_id: str
    lead_outreach_id: str | None = None
    provider_key: str
    external_crm_id: str | None = None
    sync_status: CrmSyncStatus = CrmSyncStatus.PENDING
    mapping: dict[str, object] = Field(default_factory=dict)
    error_message: str | None = None
    synced_at: str | None = None
    next_sync_at: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class InboundReplyEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    lead_id: str
    lead_outreach_id: str
    provider_name: str
    thread_id: str | None = None
    provider_message_id: str | None = None
    from_email: str
    to_email: str
    subject: str
    body: str
    received_at: str
    metadata: dict[str, object] = Field(default_factory=dict)
