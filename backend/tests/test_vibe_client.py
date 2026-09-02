from unittest.mock import Mock, patch

from app.integrations.vibe import VibeProspectingClient


def test_vibe_client_maps_only_supported_fields_and_evidence() -> None:
    response = Mock()
    response.json.return_value = {"data": {"company_name": "Datamart", "employee_count": 12, "ignored": "x", "evidence": [{"title": "Company site", "source_url": "https://example.com", "supports_fields": ["company_name"]}]}}
    response.raise_for_status.return_value = None
    with patch("app.integrations.vibe.client.httpx.post", return_value=response) as post:
        result = VibeProspectingClient("https://vibe.example/enrich", "secret").enrich({"id": "lead-1", "company_name": "Old"})
    assert result.fields == {"company_name": "Datamart", "employee_count": 12}
    assert result.evidence[0].source_url == "https://example.com"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"
