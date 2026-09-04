from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GenerateOutreachRequest(BaseModel):
    lead_id: str
    channel: Literal["email", "linkedin"] = "email"


class ReviewOutreachRequest(BaseModel):
    action: Literal["approved", "rejected"]
    review_notes: str = Field(min_length=1, max_length=2000)


class SendEmailRequest(BaseModel):
    confirm: Literal[True]


class SaveOutreachDraftRequest(BaseModel):
    subject: str | None = None
    body: str


class RegenerateOutreachRequest(BaseModel):
    reason: str | None = None


class PauseSequenceRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RunDueFollowupsRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)


class IngestInboundReplyRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=100)
    lead_outreach_id: str = Field(min_length=1)
    thread_id: str | None = None
    provider_message_id: str | None = None
    from_email: str = Field(min_length=3)
    to_email: str = Field(min_length=3)
    subject: str = ""
    body: str = Field(min_length=1)
    received_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)

class CrmSyncRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=100)
    mapping: dict[str, object] = Field(default_factory=dict)

