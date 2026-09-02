from unittest.mock import Mock, patch

from app.integrations.vibe import VibeProspectingClient


def test_vibe_client_matches_then_enriches_with_agentsource() -> None:
    match_response = Mock()
    match_response.json.return_value = {"matched_prospects": [{"prospect_id": "abc123"}]}
    match_response.raise_for_status.return_value = None
    profile_response = Mock()
    profile_response.json.return_value = {"data": {"full_name": "Aisha Rafiq", "job_title": "Founder", "company_name": "Datamart", "country_name": "Pakistan", "ignored": "x"}}
    profile_response.raise_for_status.return_value = None
    with patch("app.integrations.vibe.client.httpx.post", side_effect=[match_response, profile_response]) as post:
        result = VibeProspectingClient("secret").enrich({"id": "lead-1", "linkedin_url": "https://linkedin.com/in/aisha", "company_name": "Old"})
    assert result.matched is True
    assert result.prospect_id == "abc123"
    assert result.fields == {"person_name": "Aisha Rafiq", "title": "Founder", "company_name": "Datamart", "country": "Pakistan"}
    assert result.evidence == []
    assert post.call_args_list[0].kwargs["json"] == {"prospects_to_match": [{"company_name": "Old", "linkedin": "https://linkedin.com/in/aisha"}]}
    assert post.call_args_list[1].args[0].endswith("/v1/prospects/profiles/enrich")
    assert post.call_args_list[0].kwargs["headers"]["api_key"] == "secret"


def test_vibe_client_completes_without_a_second_call_when_no_match() -> None:
    match_response = Mock()
    match_response.json.return_value = {"matched_prospects": [{"prospect_id": None}]}
    match_response.raise_for_status.return_value = None
    with patch("app.integrations.vibe.client.httpx.post", return_value=match_response) as post:
        result = VibeProspectingClient("secret").enrich({"id": "lead-1", "linkedin_url": "https://linkedin.com/in/no-match"})
    assert result.matched is False
    assert result.fields == {}
    assert result.prospect_id is None
    assert post.call_count == 1


def test_vibe_client_whitelists_safe_fields_and_builds_evidence() -> None:
    match_response = Mock()
    match_response.json.return_value = {"matched_prospects": [{"prospect_id": "abc123"}]}
    match_response.raise_for_status.return_value = None
    profile_response = Mock()
    profile_response.json.return_value = {
        "data": {
            "full_name": "Aisha Rafiq",
            "job_title": "Founder",
            "company_name": "Datamart",
            "country_name": "Pakistan",
            "annual_revenue": 1000000,
            "status": "active",
            "evidence": [
                {
                    "title": "Founder profile",
                    "source_url": "https://example.com/founder",
                    "evidence_type": "other",
                    "publisher": "AgentSource",
                    "excerpt": "Strong fit",
                    "supports_fields": ["person_name", "title"],
                    "metadata": {"confidence": 0.92},
                }
            ],
        }
    }
    profile_response.raise_for_status.return_value = None

    with patch("app.integrations.vibe.client.httpx.post", side_effect=[match_response, profile_response]):
        result = VibeProspectingClient("secret").enrich({"id": "lead-1", "linkedin_url": "https://linkedin.com/in/aisha", "company_name": "Old"})

    assert result.fields == {"person_name": "Aisha Rafiq", "title": "Founder", "company_name": "Datamart", "country": "Pakistan"}
    assert result.evidence[0].title == "Founder profile"
    assert result.evidence[0].supports_fields == ["person_name", "title"]
    assert "annual_revenue" not in result.fields
    assert "status" not in result.fields

