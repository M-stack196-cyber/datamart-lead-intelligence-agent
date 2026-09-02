from unittest.mock import Mock, patch

from app.intent import CaptureResult, LiveCaptureAgent


def test_capture_agent_scores_and_enriches_a_matched_lead() -> None:
    enrichment = Mock()
    enrichment.matched = True
    enrichment.fields = {"person_name": "Aisha Rafiq", "title": "Founder", "company_name": "Datamart"}
    enrichment.evidence = [
        {"title": "Hiring expansion", "source_url": "https://example.com/hiring", "excerpt": "Hiring product and GTM leaders"},
        {"title": "Funding round", "source_url": "https://example.com/funding"},
    ]

    lead = {
        "person_name": "Aisha Rafiq",
        "company_name": "Datamart",
        "title": "Founder",
        "email": "aisha@datamart.ai",
        "linkedin_url": "https://linkedin.com/in/aisha",
    }

    with patch("app.intent.capture.VibeProspectingClient.enrich", return_value=enrichment):
        result = LiveCaptureAgent("secret").capture(lead)

    assert result.matched is True
    assert result.intent.score >= 70
    assert result.intent.level in {"high", "medium"}
    assert result.evidence_urls == ["https://example.com/hiring", "https://example.com/funding"]
    assert result.normalized_fields["person_name"] == "Aisha Rafiq"


def test_capture_agent_rejects_unmatched_leads_without_intent() -> None:
    enrichment = Mock()
    enrichment.matched = False
    enrichment.fields = {}
    enrichment.evidence = []

    with patch("app.intent.capture.VibeProspectingClient.enrich", return_value=enrichment):
        result = LiveCaptureAgent("secret").capture({"company_name": "Unknown"})

    assert result.matched is False
    assert result.intent.score < 50
    assert result.intent.level == "low"
    assert result.evidence_urls == []
