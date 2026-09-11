from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.lead_sources.base import NormalizedLead


class ApolloCsvLeadSourceProvider:
    """Apollo CSV export adapter for temporary local test batches."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def fetch_leads(self, limit: int | None = None) -> list[NormalizedLead]:
        if limit is not None and limit < 1:
            raise ValueError("Apollo CSV import limit must be at least one")

        with self.file_path.open(newline="", encoding="utf-8-sig") as csv_file:
            rows = list(csv.DictReader(csv_file))

        leads = [self._normalize_row(row) for row in rows]
        return leads if limit is None else leads[:limit]

    @classmethod
    def _normalize_row(cls, row: dict[str, Any]) -> NormalizedLead:
        return NormalizedLead(
            person_name=cls._full_name(row),
            title=cls._string(row.get("Title")),
            company_name=cls._first_string(
                row.get("Company Name"),
                row.get("Company Name for Emails"),
            ),
            company_url=cls._string(row.get("Website")),
            linkedin_url=cls._string(row.get("Person Linkedin Url")),
            email=cls._email(row),
            phone=cls._phone(row),
            country=cls._first_string(row.get("Country"), row.get("Company Country")),
            employee_count=cls._int(row.get("# Employees")),
            industry=cls._string(row.get("Industry")),
            source="apollo_csv",
            source_id=cls._first_string(
                row.get("Apollo Contact Id"),
                row.get("Apollo Record Id"),
            ),
            raw_source_data=dict(row),
        )

    @classmethod
    def _full_name(cls, row: dict[str, Any]) -> str | None:
        return " ".join(
            part
            for part in (
                cls._string(row.get("First Name")),
                cls._string(row.get("Last Name")),
            )
            if part
        ) or None

    @staticmethod
    def _string(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _first_string(cls, *values: Any) -> str | None:
        for value in values:
            if text := cls._string(value):
                return text
        return None

    @classmethod
    def _email(cls, row: dict[str, Any]) -> str | None:
        email = cls._string(row.get("Email"))
        if not email:
            return None

        status = cls._string(row.get("Email Status"))
        if (status and status.casefold() == "verified") or "@" in email:
            return email
        return None

    @classmethod
    def _phone(cls, row: dict[str, Any]) -> str | None:
        for key in ("Work Direct Phone", "Mobile Phone", "Corporate Phone"):
            if value := cls._string(row.get(key)):
                return value
        return None

    @staticmethod
    def _int(value: Any) -> int | None:
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            return int(str(value).strip().replace(",", ""))
        except ValueError:
            return None
