from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GenerateOutreachRequest(BaseModel):
    lead_id: str
    channel: Literal["email", "linkedin"] = "email"


class ReviewOutreachRequest(BaseModel):
    action: Literal["approved", "rejected", "approve", "reject", "needs_edit"]
    review_notes: str = Field(min_length=1, max_length=2000)


class DraftStatusReviewRequest(BaseModel):
    action: Literal["approve", "reject", "needs_edit"]
    review_notes: str = Field(min_length=1, max_length=2000)


class ManualSendRequest(BaseModel):
    review_notes: str | None = Field(default=None, max_length=2000)
    reply_wait_days: int | None = Field(default=None, ge=1, le=365)
    next_followup_decision_at: datetime | None = None
    sender_account_id: str | None = None
    sent_from_email: str | None = Field(default=None, max_length=320)


class ReplyWaitRequest(BaseModel):
    reply_wait_days: int | None = Field(default=None, ge=1, le=365)
    next_followup_decision_at: datetime | None = None


class SenderAccountCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    email_address: str = Field(min_length=3, max_length=320)
    provider: Literal["manual_only", "gmail_oauth", "smtp"] = "manual_only"
    daily_send_limit: int | None = Field(default=None, ge=1, le=10000)


class SenderAccountUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email_address: str | None = Field(default=None, min_length=3, max_length=320)
    provider: Literal["manual_only", "gmail_oauth", "smtp"] | None = None
    daily_send_limit: int | None = Field(default=None, ge=1, le=10000)
    status: Literal["not_connected", "connected", "disabled", "error"] | None = None
    is_active: bool | None = None


class NextFollowupDraftRequest(BaseModel):
    channel: Literal["email", "linkedin", "both"] = "both"
    source: str = Field(default="apollo_csv", min_length=1, max_length=100)


class PrimaryDraftRequest(BaseModel):
    channel: Literal["email", "linkedin", "both"] = "both"
    source: str = Field(default="apollo_csv", min_length=1, max_length=100)


class SendEmailRequest(BaseModel):
    confirm: Literal[True]
    sender_account_id: str
    reply_wait_days: int | None = Field(default=None, ge=1, le=365)
    next_followup_decision_at: datetime | None = None


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
