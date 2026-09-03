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
