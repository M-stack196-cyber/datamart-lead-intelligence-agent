from app.intent.engine import IntentScore
from app.services.decision import DecisionOutcome, DecisionEngine


def test_decision_engine_approves_only_when_icp_and_intent_are_both_strong() -> None:
    result = DecisionEngine().decide(
        lead={"company_name": "Datamart", "title": "Founder"},
        icp_score=82,
        intent=IntentScore(score=85, level="high", reasons=["Evidence available"], evidence_urls=["https://example.com/hiring"]),
    )

    assert result.status == "approve"
    assert result.score >= 80
    assert "Evidence-backed" in " ".join(result.reasons)


def test_decision_engine_rejects_low_intent_or_disqualified_icp() -> None:
    result = DecisionEngine().decide(
        lead={"company_name": "Datamart", "title": "Founder"},
        icp_score=30,
        intent=IntentScore(score=35, level="low", reasons=["No supporting evidence; intent cannot be validated"], evidence_urls=[]),
    )

    assert result.status == "reject"
    assert result.score < 50
