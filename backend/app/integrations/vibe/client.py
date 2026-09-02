"""Explicit AgentSource adapter for approved lead enrichment only."""

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
    matched: bool
    prospect_id: str | None
    raw_result: dict[str, Any]


class VibeProspectingClient:
    """Use AgentSource Match, then Profiles Enrich; never scrape or message LinkedIn."""

    def __init__(self, api_key: str, base_url: str = "https://api.explorium.ai") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "api_key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _prospect_input(lead: dict[str, Any]) -> dict[str, Any]:
        values = {
            "full_name": lead.get("person_name"),
            "company_name": lead.get("company_name"),
            "email": lead.get("email"),
            "linkedin": lead.get("linkedin_url"),
        }
        return {key: value for key, value in values.items() if value not in (None, "")}

    @staticmethod
    def _prospect_id(body: dict[str, Any]) -> str | None:
        matches = body.get("matched_prospects")
        if not isinstance(matches, list) or not matches:
            return None
        first = matches[0]
        if not isinstance(first, dict):
            return None
        prospect_id = first.get("prospect_id")
        return str(prospect_id) if prospect_id else None

    @staticmethod
    def _supported_fields(data: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "full_name": "person_name",
            "job_title": "title",
            "company_name": "company_name",
            "country_name": "country",
        }
        return {
            target: data[source]
            for source, target in mapping.items()
            if data.get(source) not in (None, "")
        }

    def enrich(self, lead: dict[str, Any]) -> VibeEnrichment:
        match_response = httpx.post(
            f"{self.base_url}/v1/prospects/match",
            json={"prospects_to_match": [self._prospect_input(lead)]},
            headers=self._headers,
            timeout=30,
        )
        match_response.raise_for_status()
        match_body = match_response.json()
        if not isinstance(match_body, dict):
            raise ValueError("AgentSource Match returned a non-object response")

        prospect_id = self._prospect_id(match_body)
        if not prospect_id:
            return VibeEnrichment(
                fields={},
                evidence=[],
                matched=False,
                prospect_id=None,
                raw_result={"match": match_body},
            )

        profile_response = httpx.post(
            f"{self.base_url}/v1/prospects/profiles/enrich",
            json={"prospect_id": prospect_id, "request_context": None, "parameters": {}},
            headers=self._headers,
            timeout=30,
        )
        profile_response.raise_for_status()
        profile_body = profile_response.json()
        if not isinstance(profile_body, dict):
            raise ValueError("AgentSource Profiles Enrich returned a non-object response")
        data = profile_body.get("data", {})
        if not isinstance(data, dict):
            data = {}
        return VibeEnrichment(
            fields=self._supported_fields(data),
            evidence=[],
            matched=True,
            prospect_id=prospect_id,
            raw_result={"match": match_body, "profile": profile_body},
        )

