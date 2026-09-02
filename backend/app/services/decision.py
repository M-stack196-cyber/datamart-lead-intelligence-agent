from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.intent.engine import IntentScore


@dataclass(frozen=True)
class DecisionOutcome:
    status: str
    score: int
    reasons: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)


class DecisionEngine:
    """Combine ICP fit and evidence-backed buying intent into a single lead-readiness decision."""

    @staticmethod
    def decide(lead: dict[str, Any], *, icp_score: int, intent: IntentScore) -> DecisionOutcome:
        score = int(icp_score * 0.6 + intent.score * 0.4)
        reasons = list(intent.reasons)

        if icp_score < 45:
            status = "reject"
            reasons.append("ICP fit is below the minimum threshold")
        elif intent.score < 50:
            status = "reject"
            reasons.append("Buying intent is not supported by evidence")
        elif score >= 75 and intent.level in {"high", "medium"}:
            status = "approve"
            reasons.append("Evidence-backed strong fit for sales review")
        else:
            status = "review"
            reasons.append("Requires human review before outbound action")

        if intent.evidence_urls:
            reasons.append("Evidence-backed")

        return DecisionOutcome(
            status=status,
            score=max(0, min(100, score)),
            reasons=reasons,
            evidence_urls=list(intent.evidence_urls),
        )
