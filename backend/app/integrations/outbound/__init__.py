"""Provider-neutral outbound execution boundaries."""

from app.integrations.outbound.mock import MockCrmProvider, MockInboundReplyProvider, MockOutboundEmailProvider
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

__all__ = [
    "CrmHandoffRequest",
    "CrmHandoffResult",
    "CrmProvider",
    "InboundReplyProvider",
    "InboundReplyRequest",
    "InboundReplyResult",
    "MockCrmProvider",
    "MockInboundReplyProvider",
    "MockOutboundEmailProvider",
    "OutboundEmailProvider",
    "OutboundEmailRequest",
    "OutboundEmailResult",
]