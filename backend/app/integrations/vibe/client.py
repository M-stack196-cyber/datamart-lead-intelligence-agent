"""Explicit adapter for an account-configured Vibe/Explorium AgentSource endpoint."""

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class VibeEvidence:
    title: str
    source_url: str
    evidence_type: str = "other"
    publisher: str | None = "Vibe Prospecting"
    excerpt: str | None = None
    supports_fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VibeEnrichment:
    fields: dict[str, Any]
    evidence: list[VibeEvidence]
    raw_result: dict[str, Any]


class VibeProspectingClient:
    """Call one approved enrichment job; no LinkedIn scraping or messaging."""

    def __init__(self, endpoint: str, api_key: str) -> None:
        self.endpoint = endpoint
        self.api_key = api_key

    def enrich(self, lead: dict[str, Any]) -> VibeEnrichment:
        response = httpx.post(
            self.endpoint,
            json={"lead": {key: lead.get(key) for key in ("id", "linkedin_url", "company_name", "company_url", "person_name", "title", "email")}, "enrichments": ["prospects_contacts", "business_firmographics"]},
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}, timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Vibe returned a non-object response")
        data = body.get("data", body)
        if not isinstance(data, dict):
            raise ValueError("Vibe response data must be an object")
        allowed = {"company_name", "person_name", "title", "company_url", "email", "country", "industry", "annual_revenue", "employee_count", "business_model", "growth_stage"}
        fields = {key: value for key, value in data.items() if key in allowed and value not in (None, "")}
        evidence = [VibeEvidence(title=str(item["title"])[:500], source_url=str(item["source_url"]), evidence_type=str(item.get("evidence_type", "other")), publisher=item.get("publisher"), excerpt=item.get("excerpt"), supports_fields=list(item.get("supports_fields", [])), metadata={"provider": "vibe", **(item.get("metadata") or {})}) for item in data.get("evidence", []) if isinstance(item, dict) and item.get("source_url") and item.get("title")]
        return VibeEnrichment(fields=fields, evidence=evidence, raw_result=body)
