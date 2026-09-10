from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class ProviderAuthError(RuntimeError):
    """Raised when a lead source rejects authentication or account access."""


class NormalizedLead(BaseModel):
    model_config = ConfigDict(frozen=True)

    person_name: str | None = None
    title: str | None = None
    company_name: str | None = None
    company_url: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    employee_count: int | None = None
    industry: str | None = None
    source: str
    source_id: str | None = None
    raw_source_data: dict[str, Any]


class LeadSourceProvider(Protocol):
    def fetch_leads(self, limit: int) -> list[NormalizedLead]:
        """Fetch and normalize leads from a provider."""
