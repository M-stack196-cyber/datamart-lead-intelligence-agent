from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntentScore:
    score: int
    level: str
    reasons: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)


class IntentEngine:
    """Evidence-backed buying-intent scoring for a lead intelligence agent."""

    @staticmethod
    def _normalize_evidence_urls(evidence: list[dict[str, Any]]) -> list[str]:
        urls: list[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            url = item.get("source_url")
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())
        return urls

    @classmethod
    def score(cls, lead: dict[str, Any], evidence: list[dict[str, Any]]) -> IntentScore:
        evidence_urls = cls._normalize_evidence_urls(evidence)
        score = 0
        reasons: list[str] = []

        if lead.get("email"):
            score += 15
            reasons.append("Direct contact available")

        if lead.get("title") and any(keyword in str(lead.get("title")).lower() for keyword in ["founder", "ceo", "cmo", "vp", "head", "director"]):
            score += 20
            reasons.append("Decision-maker title")

        if lead.get("growth_stage"):
            score += 10
            reasons.append(f"Growth stage signal: {lead['growth_stage']}")

        if any(keyword in str(lead.get("company_name", "")).lower() for keyword in ["ai", "saas", "cloud", "platform", "labs", "studio"]):
            score += 10
            reasons.append("Company profile aligns with software growth patterns")

        if evidence:
            score += 25
            reasons.append("Evidence available for the lead")
            for item in evidence[:2]:
                text = (item.get("excerpt") or item.get("title") or "").strip()
                if "hiring" in text.lower() or "raise" in text.lower() or "funding" in text.lower() or "expands" in text.lower() or "launch" in text.lower():
                    score += 15
                    reasons.append("Hiring or expansion signal")
                    break
        else:
            score -= 20
            reasons.append("No supporting evidence; intent cannot be validated")

        if score >= 70:
            level = "high"
        elif score >= 45:
            level = "medium"
        else:
            level = "low"

        if level == "low" and not evidence:
            reasons.append("Evidence is required before classifying buying intent")

        return IntentScore(
            score=max(0, min(100, score)),
            level=level,
            reasons=reasons,
            evidence_urls=evidence_urls,
        )
