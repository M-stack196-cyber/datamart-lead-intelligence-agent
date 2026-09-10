from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.lead_sources.base import NormalizedLead, ProviderAuthError


APOLLO_AUTH_ERROR = (
    "Apollo API rejected the request. Check APOLLO_API_KEY, plan access, or credits."
)


class ApolloLeadSourceProvider:
    """Apollo People Search adapter for ICP discovery."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.api_key = api_key if api_key is not None else settings.apollo_api_key
        self.base_url = (base_url or settings.apollo_base_url).rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "x-api-key": self.api_key or "",
        }

    def fetch_leads(self, limit: int) -> list[NormalizedLead]:
        if not self.api_key:
            raise ProviderAuthError("APOLLO_API_KEY is not configured.")
        if limit < 1:
            raise ValueError("Apollo discovery limit must be at least one")

        response = httpx.post(
            f"{self.base_url}/api/v1/mixed_people/api_search",
            headers=self._headers,
            json=self._search_payload(limit),
            timeout=30,
        )
        if response.status_code in {401, 403}:
            raise ProviderAuthError(APOLLO_AUTH_ERROR)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError("Apollo API request failed") from exc

        body = response.json()
        return [
            lead
            for row in self._people_rows(body)
            if (lead := self._normalize_person(row)) is not None
        ][:limit]

    @staticmethod
    def _search_payload(limit: int) -> dict[str, Any]:
        return {
            "page": 1,
            "per_page": min(limit, 100),
            "person_seniorities": [
                "owner",
                "founder",
                "c_suite",
                "partner",
                "vp",
                "head",
                "director",
            ],
            "person_titles": [
                "Founder",
                "Co-Founder",
                "CEO",
                "CTO",
                "VP Engineering",
                "Head of Engineering",
                "Director of Engineering",
                "Owner",
                "Managing Director",
                "Operations Director",
                "IT Director",
                "Practice Manager",
                "Partner",
            ],
            "organization_locations": ["United States", "United Arab Emirates"],
            "organization_num_employees_ranges": ["1,10", "11,50"],
            "contact_email_status": ["verified", "likely to engage"],
        }

    @staticmethod
    def _people_rows(body: Any) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        for key in ("people", "contacts", "persons"):
            rows = body.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        data = body.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            return ApolloLeadSourceProvider._people_rows(data)
        return []

    @classmethod
    def _normalize_person(cls, row: dict[str, Any]) -> NormalizedLead | None:
        organization = cls._organization(row)
        email = cls._email(row)
        employee_count = cls._employee_count(organization)
        source_id = cls._string(row.get("id") or row.get("person_id"))

        return NormalizedLead(
            person_name=cls._string(row.get("name") or cls._full_name(row)),
            title=cls._string(row.get("title") or row.get("headline")),
            company_name=cls._string(
                organization.get("name")
                or row.get("organization_name")
                or row.get("company_name")
            ),
            company_url=cls._company_url(organization, row),
            linkedin_url=cls._string(row.get("linkedin_url") or row.get("linkedin")),
            email=email,
            phone=cls._phone(row),
            country=cls._string(
                organization.get("country")
                or row.get("organization_country")
                or row.get("country")
            ),
            employee_count=employee_count,
            industry=cls._string(organization.get("industry") or row.get("industry")),
            source="apollo",
            source_id=source_id,
            raw_source_data=dict(row),
        )

    @staticmethod
    def _organization(row: dict[str, Any]) -> dict[str, Any]:
        organization = row.get("organization") or row.get("account")
        return organization if isinstance(organization, dict) else {}

    @staticmethod
    def _string(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _full_name(row: dict[str, Any]) -> str | None:
        return " ".join(
            part
            for part in (
                ApolloLeadSourceProvider._string(row.get("first_name")),
                ApolloLeadSourceProvider._string(row.get("last_name")),
            )
            if part
        ) or None

    @staticmethod
    def _company_url(organization: dict[str, Any], row: dict[str, Any]) -> str | None:
        return ApolloLeadSourceProvider._string(
            organization.get("website_url")
            or organization.get("website")
            or organization.get("primary_domain")
            or row.get("organization_website_url")
            or row.get("company_url")
            or row.get("company_website")
        )

    @staticmethod
    def _email(row: dict[str, Any]) -> str | None:
        for key in ("verified_email", "work_email", "email"):
            value = ApolloLeadSourceProvider._string(row.get(key))
            if value and "@" in value and "[email" not in value.casefold():
                return value
        return None

    @staticmethod
    def _phone(row: dict[str, Any]) -> str | None:
        for key in ("phone", "sanitized_phone", "mobile_phone", "organization_phone"):
            if value := ApolloLeadSourceProvider._string(row.get(key)):
                return value
        return None

    @staticmethod
    def _employee_count(organization: dict[str, Any]) -> int | None:
        for key in (
            "estimated_num_employees",
            "num_employees",
            "employee_count",
            "headcount",
        ):
            value = organization.get(key)
            if isinstance(value, bool) or value in (None, ""):
                continue
            try:
                return int(str(value).replace(",", ""))
            except ValueError:
                continue
        return None
