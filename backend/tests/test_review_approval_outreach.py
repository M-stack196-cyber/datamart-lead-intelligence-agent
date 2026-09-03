from app.services.approval import ApprovalEngine
import pytest

from app.services.outreach import OutreachDraftEngine, validate_outreach_for_approval


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
            {"id": "evidence-1", "title": "Hiring expansion", "source_url": "https://example.com/hiring", "publisher": "Example"},
        ],
        channel="email",
    )

    assert draft["subject"].lower().startswith("datamart")
    assert "Aisha" in draft["body"]
    assert "https://example.com/hiring" in draft["body"]
    assert draft["channel"] == "email"
    assert draft["evidence_ids"] == ["evidence-1"]


def test_outreach_requires_stored_evidence_and_rejects_unsupported_activity_claims() -> None:
    with pytest.raises(ValueError, match="Stored evidence"):
        OutreachDraftEngine().draft({"company_name": "Unknown"}, [], channel="email")

    with pytest.raises(ValueError, match="Unsupported personal activity claim"):
        validate_outreach_for_approval(
            "Hi Aisha, I saw your LinkedIn post about hiring.",
            [{"id": "evidence-1", "source_url": "https://example.com/hiring"}],
        )

    with pytest.raises(ValueError, match="factual claim"):
        validate_outreach_for_approval(
            "Hi Aisha, your company raised $20M and is expanding.",
            [{"id": "evidence-1", "source_url": "https://example.com/company", "title": "Company profile"}],
            {"person_name": "Aisha", "company_name": "Example"},
        )


def test_outreach_allows_a_factual_signal_when_it_is_in_stored_evidence() -> None:
    validate_outreach_for_approval(
        "A public source reports that Example is hiring.",
        [{"id": "evidence-1", "source_url": "https://example.com/jobs", "title": "Example is hiring"}],
        {"company_name": "Example"},
    )
