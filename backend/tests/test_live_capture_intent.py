from app.intent.engine import IntentEngine


def test_intent_engine_requires_evidence_for_high_intent() -> None:
    engine = IntentEngine()
    lead = {
        "person_name": "Aisha Rafiq",
        "company_name": "Datamart",
        "title": "Founder",
        "email": "aisha@datamart.ai",
        "linkedin_url": "https://linkedin.com/in/aisha",
    }

    result = engine.score(lead, evidence=[])

    assert result.score < 50
    assert result.level == "low"
    assert any("evidence" in reason.lower() for reason in result.reasons)


def test_intent_engine_rewards_evidence_and_buying_signals() -> None:
    engine = IntentEngine()
    lead = {
        "person_name": "Aisha Rafiq",
        "company_name": "Datamart",
        "title": "Founder",
        "email": "aisha@datamart.ai",
        "linkedin_url": "https://linkedin.com/in/aisha",
        "growth_stage": "Series A",
    }
    evidence = [
        {"title": "Datamart expands platform team", "source_url": "https://example.com/hiring", "excerpt": "Hiring product and GTM leaders"},
        {"title": "Company raises funding", "source_url": "https://example.com/funding"},
    ]

    result = engine.score(lead, evidence=evidence)

    assert result.score >= 70
    assert result.level in {"high", "medium"}
    assert "Hiring" in " ".join(result.reasons)
    assert result.evidence_urls == ["https://example.com/hiring", "https://example.com/funding"]
