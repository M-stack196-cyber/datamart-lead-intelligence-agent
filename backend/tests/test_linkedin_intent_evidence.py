from app.workers import runner


def test_linkedin_post_evidence_is_preserved():
    item = runner._evidence_dict(
        {
            "title": "AI hiring update",
            "source_url": "https://www.linkedin.com/posts/test-123",
            "evidence_type": "linkedin_post",
            "publisher": "LinkedIn",
            "excerpt": "We are expanding our AI team.",
            "activity_at": "2026-09-04T10:00:00Z",
            "intent_signal": "ai_hiring",
            "intent_reason": "Company is actively expanding AI capability.",
            "intent_score_delta": 20,
            "supports_fields": ["intent"],
        }
    )

    assert item is not None
    assert item["evidence_type"] == "linkedin_post"
    assert item["activity_at"] == "2026-09-04T10:00:00Z"
    assert item["intent_signal"] == "ai_hiring"
    assert item["intent_score_delta"] == 20


def test_linkedin_comment_is_not_converted_to_other():
    item = runner._evidence_dict(
        {
            "title": "CRM automation comment",
            "source_url": "https://www.linkedin.com/feed/update/test-comment",
            "evidence_type": "linkedin_comment",
            "excerpt": "Which CRM automation platform are you using?",
            "activity_at": "2026-09-03T08:00:00Z",
            "intent_signal": "crm_interest",
            "intent_reason": "Prospect is actively discussing CRM automation.",
            "intent_score_delta": 15,
        }
    )

    assert item is not None
    assert item["evidence_type"] == "linkedin_comment"


def test_linkedin_activity_is_supported():
    item = runner._evidence_dict(
        {
            "title": "Automation engagement",
            "source_url": "https://www.linkedin.com/posts/activity-456",
            "evidence_type": "linkedin_activity",
            "activity_at": "2026-09-02T12:00:00Z",
            "intent_signal": "automation_interest",
            "intent_reason": "Prospect engaged with automation content.",
            "intent_score_delta": 10,
        }
    )

    assert item is not None
    assert item["evidence_type"] == "linkedin_activity"


from app.intent import IntentEngine


def test_linkedin_evidence_affects_intent_score():
    lead = {
        "company_name": "Test SaaS",
        "title": "CEO",
        "email": "ceo@example.com",
    }

    evidence = [
        {
            "title": "AI automation post",
            "source_url": (
                "https://www.linkedin.com/posts/"
                "intent-test"
            ),
            "evidence_type": "linkedin_post",
            "excerpt": (
                "We are looking at AI automation "
                "for our operations."
            ),
            "intent_signal": "automation_interest",
            "intent_reason": (
                "Prospect is actively discussing "
                "AI automation."
            ),
            "intent_score_delta": 20,
        }
    ]

    result = IntentEngine.score(
        lead,
        evidence,
    )

    assert result.score >= 20
    assert (
        "Prospect is actively discussing "
        "AI automation."
        in result.reasons
    )

    assert (
        "LinkedIn activity provides "
        "direct intent evidence"
        in result.reasons
    )


def test_linkedin_delta_is_capped():
    lead = {
        "company_name": "Test Company",
    }

    evidence = [
        {
            "title": f"Signal {index}",
            "source_url": (
                "https://linkedin.com/posts/"
                + str(index)
            ),
            "evidence_type": (
                "linkedin_activity"
            ),
            "intent_score_delta": 30,
        }
        for index in range(5)
    ]

    result = IntentEngine.score(
        lead,
        evidence,
    )

    assert result.score <= 100
