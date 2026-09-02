from app.services.approval import ApprovalEngine
from app.services.outreach import OutreachDraftEngine


def test_approval_engine_approves_only_evidence_backed_quality_leads() -> None:
    result = ApprovalEngine().decide(
        {
            "company_name": "Datamart",
            "title": "Founder",
            "person_name": "Aisha Rafiq",
        },
        icp_score=82,
        intent_score=84,
        evidence_urls=["https://example.com/hiring"],
    )

    assert result.status == "approved"
    assert result.score >= 80
    assert "evidence" in " ".join(result.reasons).lower()


def test_approval_engine_blocks_weak_or_unsupported_leads() -> None:
    result = ApprovalEngine().decide(
        {"company_name": "Unknown", "title": "Intern"},
        icp_score=35,
        intent_score=30,
        evidence_urls=[],
    )

    assert result.status == "rejected"
    assert result.score < 50


def test_outreach_draft_engine_creates_reviewable_message_with_evidence() -> None:
    draft = OutreachDraftEngine().draft(
        {
            "person_name": "Aisha Rafiq",
            "company_name": "Datamart",
            "title": "Founder",
        },
        [
            {"title": "Hiring expansion", "source_url": "https://example.com/hiring"},
        ],
        channel="email",
    )

    assert draft["subject"].lower().startswith("datamart")
    assert "Aisha" in draft["body"]
    assert "https://example.com/hiring" in draft["body"]
    assert draft["channel"] == "email"
