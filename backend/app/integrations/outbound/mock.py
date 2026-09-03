from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.integrations.outbound.providers import (
    CrmHandoffRequest,
    CrmHandoffResult,
    CrmProvider,
    InboundReplyProvider,
    InboundReplyRequest,
    InboundReplyResult,
    OutboundEmailProvider,
    OutboundEmailRequest,
    OutboundEmailResult,
)


class MockOutboundEmailProvider:
    def __init__(self) -> None:
        self.sent_requests: list[OutboundEmailRequest] = []

    def send(self, request: OutboundEmailRequest) -> OutboundEmailResult:
        self.sent_requests.append(request)
        return OutboundEmailResult(
            provider_name=request.provider_name,
            provider_message_id=f"mock-email-{uuid4().hex}",
            status="sent",
            sent_at=datetime.now(tz=UTC),
            raw_response={"provider": request.provider_name, "idempotency_key": request.idempotency_key},
        )


class MockInboundReplyProvider:
    def __init__(self) -> None:
        self.captured_requests: list[InboundReplyRequest] = []

    def ingest_reply(self, request: InboundReplyRequest) -> InboundReplyResult:
        self.captured_requests.append(request)
        return InboundReplyResult(
            provider_name=request.provider_name,
            reply_id=f"mock-reply-{uuid4().hex}",
            lead_id=request.lead_id,
            lead_outreach_id=request.lead_outreach_id,
            status="stored",
            received_at=request.received_at,
            raw_response={"thread_id": request.thread_id, "provider_message_id": request.provider_message_id},
        )


class MockCrmProvider:
    def __init__(self) -> None:
        self.pushed_requests: list[CrmHandoffRequest] = []

    def push(self, request: CrmHandoffRequest) -> CrmHandoffResult:
        self.pushed_requests.append(request)
        return CrmHandoffResult(
            provider_key=request.provider_key,
            external_crm_id=request.external_crm_id or f"mock-crm-{uuid4().hex}",
            sync_status="synced",
            synced_at=datetime.now(tz=UTC),
            raw_response={"mapping_keys": sorted(request.mapping)},
        )


__all__ = [
    "MockOutboundEmailProvider",
    "MockInboundReplyProvider",
    "MockCrmProvider",
]