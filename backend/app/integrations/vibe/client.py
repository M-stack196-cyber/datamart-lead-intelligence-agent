"""Explorium AgentSource adapter for prospect discovery and lead enrichment."""

from dataclasses import asdict, dataclass, field
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


@dataclass(frozen=True)
class VibeDiscoveryResult:
    prospects: list[dict[str, Any]]
    total_results: int
    page: int
    total_pages: int
    raw_result: dict[str, Any]


class VibeProspectingClient:
    """
    Explorium AgentSource client.

    Responsibilities:
    - discover prospects from Vibe/Explorium
    - match known prospects
    - enrich matched prospects

    LinkedIn content/activity evidence is handled separately.
    """

    SAFE_FIELD_MAP = {
        "full_name": "person_name",
        "job_title": "title",
        "company_name": "company_name",
        "country_name": "country",
        "country": "country",
        "industry": "industry",
        "email": "email",
        "linkedin": "linkedin_url",
        "linkedin_url": "linkedin_url",
    }

    DISCOVERY_FIELD_MAP = {
        **SAFE_FIELD_MAP,
        "company_website": "company_url",
        "company_url": "company_url",
        "annual_revenue": "annual_revenue",
        "company_revenue": "annual_revenue",
        "employee_count": "employee_count",
        "company_employee_count": "employee_count",
        "business_model": "business_model",
        "growth_stage": "growth_stage",
        "buying_behavior": "buying_behavior",
        "has_funding_or_revenue": "has_funding_or_revenue",
        "has_defined_software_need": "has_defined_software_need",
        "has_technical_stakeholder": "has_technical_stakeholder",
        "accepts_distributed_delivery": "accepts_distributed_delivery",
    }

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.explorium.ai",
    ) -> None:
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
    def _prospect_input(
        lead: dict[str, Any],
    ) -> dict[str, Any]:
        values = {
            "full_name": lead.get("person_name"),
            "company_name": lead.get("company_name"),
            "email": lead.get("email"),
            "linkedin": lead.get("linkedin_url"),
        }

        return {
            key: value
            for key, value in values.items()
            if value not in (None, "")
        }

    @staticmethod
    def _prospect_id(
        body: dict[str, Any],
    ) -> str | None:
        matches = body.get("matched_prospects")

        if not isinstance(matches, list) or not matches:
            return None

        first = matches[0]

        if not isinstance(first, dict):
            return None

        prospect_id = first.get("prospect_id")

        return str(prospect_id) if prospect_id else None

    @classmethod
    def _supported_fields(
        cls,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            target: value
            for source, target in cls.SAFE_FIELD_MAP.items()
            if (value := data.get(source)) not in (None, "")
        }

    @classmethod
    def _normalize_discovered_prospect(
        cls,
        prospect: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = {
            target: value
            for source, target in cls.DISCOVERY_FIELD_MAP.items()
            if (value := prospect.get(source)) not in (None, "")
        }

        prospect_id = (
            prospect.get("prospect_id")
            or prospect.get("id")
        )

        if prospect_id:
            normalized["vibe_prospect_id"] = str(prospect_id)

        if prospect.get("business_id"):
            normalized["vibe_business_id"] = str(
                prospect["business_id"]
            )

        if prospect.get("job_department"):
            normalized["job_department"] = prospect[
                "job_department"
            ]

        if prospect.get("job_level_main"):
            normalized["job_level"] = prospect[
                "job_level_main"
            ]

        if prospect.get("company_linkedin"):
            normalized["company_linkedin_url"] = prospect[
                "company_linkedin"
            ]

        evidence = [
            asdict(item)
            for item in cls._evidence_items(prospect)
        ]

        if evidence:
            normalized["evidence"] = evidence

        return normalized

    @staticmethod
    def _evidence_items(
        data: dict[str, Any],
    ) -> list[VibeEvidence]:
        evidence = data.get("evidence")

        if not isinstance(evidence, list):
            return []

        items: list[VibeEvidence] = []

        for item in evidence:
            if not isinstance(item, dict):
                continue

            url = item.get("source_url")
            title = item.get("title")

            if (
                not isinstance(url, str)
                or not url
                or not isinstance(title, str)
                or not title
            ):
                continue

            items.append(
                VibeEvidence(
                    title=title,
                    source_url=url,
                    evidence_type=str(
                        item.get(
                            "evidence_type",
                            "other",
                        )
                    ),
                    publisher=item.get("publisher"),
                    excerpt=item.get("excerpt"),
                    supports_fields=(
                        item.get("supports_fields")
                        if isinstance(
                            item.get("supports_fields"),
                            list,
                        )
                        else []
                    ),
                    metadata=(
                        item.get("metadata")
                        if isinstance(
                            item.get("metadata"),
                            dict,
                        )
                        else {}
                    ),
                )
            )

        return items

    def discover(
        self,
        *,
        filters: dict[str, Any],
        size: int = 25,
        page_size: int = 25,
        page: int = 1,
    ) -> VibeDiscoveryResult:
        """
        Automatically fetch prospects from Explorium.

        Filters should come from the approved Datamart ICP,
        rather than being hard-coded into the Vibe adapter.
        """

        if size < 1 or size > 60000:
            raise ValueError(
                "size must be between 1 and 60000"
            )

        if page_size < 1 or page_size > 500:
            raise ValueError(
                "page_size must be between 1 and 500"
            )

        if page < 1:
            raise ValueError(
                "page must be at least 1"
            )

        response = httpx.post(
            f"{self.base_url}/v1/prospects",
            json={
                "mode": "full",
                "size": size,
                "page_size": page_size,
                "page": page,
                "filters": filters,
                "request_context": None,
            },
            headers=self._headers,
            timeout=30,
        )

        response.raise_for_status()

        body = response.json()

        if not isinstance(body, dict):
            raise ValueError(
                "AgentSource prospect fetch returned "
                "a non-object response"
            )

        raw_prospects = body.get("data", [])

        if not isinstance(raw_prospects, list):
            raise ValueError(
                "AgentSource prospect fetch returned "
                "invalid prospect data"
            )

        prospects = [
            self._normalize_discovered_prospect(item)
            for item in raw_prospects
            if isinstance(item, dict)
        ]

        return VibeDiscoveryResult(
            prospects=prospects,
            total_results=int(
                body.get("total_results") or 0
            ),
            page=int(
                body.get("page") or page
            ),
            total_pages=int(
                body.get("total_pages") or 0
            ),
            raw_result=body,
        )

    def enrich(
        self,
        lead: dict[str, Any],
    ) -> VibeEnrichment:
        match_response = httpx.post(
            f"{self.base_url}/v1/prospects/match",
            json={
                "prospects_to_match": [
                    self._prospect_input(lead)
                ]
            },
            headers=self._headers,
            timeout=30,
        )

        match_response.raise_for_status()

        match_body = match_response.json()

        if not isinstance(match_body, dict):
            raise ValueError(
                "AgentSource Match returned "
                "a non-object response"
            )

        prospect_id = self._prospect_id(
            match_body
        )

        if not prospect_id:
            return VibeEnrichment(
                fields={},
                evidence=[],
                matched=False,
                prospect_id=None,
                raw_result={
                    "match": match_body
                },
            )

        profile_response = httpx.post(
            (
                f"{self.base_url}"
                "/v1/prospects/profiles/enrich"
            ),
            json={
                "prospect_id": prospect_id,
                "request_context": None,
                "parameters": {},
            },
            headers=self._headers,
            timeout=30,
        )

        profile_response.raise_for_status()

        profile_body = profile_response.json()

        if not isinstance(profile_body, dict):
            raise ValueError(
                "AgentSource Profiles Enrich returned "
                "a non-object response"
            )

        data = profile_body.get(
            "data",
            {},
        )

        if not isinstance(data, dict):
            data = {}

        return VibeEnrichment(
            fields=self._supported_fields(data),
            evidence=self._evidence_items(data),
            matched=True,
            prospect_id=prospect_id,
            raw_result={
                "match": match_body,
                "profile": profile_body,
            },
        )
