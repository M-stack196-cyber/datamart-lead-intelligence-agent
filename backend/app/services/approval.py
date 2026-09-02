from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApprovalDecision:
    status: str
    score: int
    reasons: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)


class ApprovalEngine:
    """Deterministic review-and-approval gate for sales handoff."""

    @staticmethod
    def decide(
        lead: dict[str, Any], *, icp_score: int, intent_score: int, evidence_urls: list[str]
    ) -> ApprovalDecision:
        score = int(icp_score * 0.65 + intent_score * 0.35)
        reasons: list[str] = []

        if icp_score < 45:
            reasons.append("ICP fit is below the minimum threshold")
            return ApprovalDecision(status="rejected", score=max(0, score), reasons=reasons, evidence_urls=list(evidence_urls))

        if intent_score < 50:
            reasons.append("Intent score is too weak to justify sales action")
            return ApprovalDecision(status="rejected", score=max(0, score), reasons=reasons, evidence_urls=list(evidence_urls))

        if not evidence_urls:
            reasons.append("No evidence is attached to the approval decision")
            return ApprovalDecision(status="rejected", score=max(0, score), reasons=reasons, evidence_urls=[])

        if score >= 80:
            status = "approved"
            reasons.append("Evidence-backed strong fit for sales review")
        else:
            status = "review"
            reasons.append("Requires human review before sales handoff")

        reasons.append("Evidence attached and verified")
        return ApprovalDecision(
            status=status,
            score=max(0, min(100, score)),
            reasons=reasons,
            evidence_urls=list(evidence_urls),
        )
