from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.integrations.vibe.client import VibeProspectingClient

from .engine import IntentEngine, IntentScore


@dataclass(frozen=True)
class CaptureResult:
    matched: bool
    normalized_fields: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)
    intent: IntentScore = field(default_factory=lambda: IntentScore(score=0, level="low", reasons=[], evidence_urls=[]))


class LiveCaptureAgent:
    """Capture and score a lead using the Vibe prospecting adapter and intent engine."""

    def __init__(self, api_key: str, client: VibeProspectingClient | None = None) -> None:
        self.api_key = api_key
        self.client = client or VibeProspectingClient(api_key)

    @staticmethod
    def _normalize_lead(lead: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key in [
            "person_name",
            "contact_name",
            "full_name",
            "company_name",
            "title",
            "job_title",
            "email",
            "linkedin_url",
            "country",
            "industry",
            "growth_stage",
        ]:
            value = lead.get(key)
            if value not in (None, ""):
                normalized[key] = value
        
        if "person_name" not in normalized and "contact_name" in normalized:
            normalized["person_name"] = normalized["contact_name"]
        if "title" not in normalized and "job_title" in normalized:
            normalized["title"] = normalized["job_title"]
        return normalized

    @staticmethod
    def _as_evidence_list(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            evidence: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    evidence.append(item)
                elif hasattr(item, "source_url") and hasattr(item, "title"):
                    converted = {"title": item.title, "source_url": item.source_url}
                    if getattr(item, "excerpt", None):
                        converted["excerpt"] = item.excerpt
                    evidence.append(converted)
            return evidence
        if isinstance(value, dict):
            return [value]
        return []

    def capture(self, lead: dict[str, Any]) -> CaptureResult:
        normalized = self._normalize_lead(lead)
        enrichment = self.client.enrich(normalized)

        matched = bool(getattr(enrichment, "matched", False))
        enrichment_fields = getattr(enrichment, "fields", {}) or {}
        if not isinstance(enrichment_fields, dict):
            enrichment_fields = {}

        pooled = {**normalized, **enrichment_fields}
        evidence = self._as_evidence_list(getattr(enrichment, "evidence", []))

        intent = IntentEngine.score(pooled, evidence)
        if not matched:
            intent = IntentEngine.score(normalized, [])

        return CaptureResult(
            matched=matched,
            normalized_fields=pooled,
            evidence=evidence,
            evidence_urls=intent.evidence_urls,
            intent=intent,
        )
