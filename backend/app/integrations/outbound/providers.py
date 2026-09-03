from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class OutboundEmailRequest:
    lead_id: str
    lead_outreach_id: str
    sequence_id: str
    step_number: int
    sender_email: str
    recipient_email: str
    subject: str
    body: str
    idempotency_key: str
    provider_name: str = "mock"
    model_name: str | None = None
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundEmailResult:
    provider_name: str
    provider_message_id: str
    status: str
    sent_at: datetime
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InboundReplyRequest:
    provider_name: str
    lead_id: str
    lead_outreach_id: str
    thread_id: str | None
    provider_message_id: str | None
    from_email: str
    to_email: str
    subject: str
    body: str
    received_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InboundReplyResult:
    provider_name: str
    reply_id: str
    lead_id: str
    lead_outreach_id: str
    status: str
    received_at: datetime
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrmHandoffRequest:
    lead_id: str
    lead_outreach_id: str
    provider_key: str
    external_crm_id: str | None
    mapping: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrmHandoffResult:
    provider_key: str
    external_crm_id: str | None
    sync_status: str
    synced_at: datetime | None
    raw_response: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class OutboundEmailProvider(Protocol):
    def send(self, request: OutboundEmailRequest) -> OutboundEmailResult: ...


@runtime_checkable
class InboundReplyProvider(Protocol):
    def ingest_reply(self, request: InboundReplyRequest) -> InboundReplyResult: ...


@runtime_checkable
class CrmProvider(Protocol):
    def push(self, request: CrmHandoffRequest) -> CrmHandoffResult: ...