from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.lead_sources.apollo_provider import APOLLO_AUTH_ERROR, ApolloLeadSourceProvider
from app.lead_sources.base import ProviderAuthError


def settings(api_key: str | None = "apollo-test-key"):
    return SimpleNamespace(
        apollo_api_key=api_key,
        apollo_base_url="https://apollo.test",
    )


def apollo_person():
    return {
        "id": "64a7ff0cc4dfae00013df1a5",
        "name": "Maya Founder",
        "title": "Founder",
        "linkedin_url": "https://linkedin.com/in/maya-founder",
        "verified_email": "maya@metricai.example",
        "phone": "+15555550123",
        "organization": {
            "name": "Metric AI",
            "website_url": "https://metricai.example",
            "estimated_num_employees": 24,
            "industry": "SaaS",
            "country": "United States",
        },
    }


def test_apollo_response_maps_to_normalized_lead(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"people": [apollo_person()]}
    response.raise_for_status.return_value = None
    monkeypatch.setattr("app.lead_sources.apollo_provider.httpx.post", Mock(return_value=response))

    leads = ApolloLeadSourceProvider(settings=settings()).fetch_leads(10)

    assert len(leads) == 1
    lead = leads[0]
    assert lead.person_name == "Maya Founder"
    assert lead.title == "Founder"
    assert lead.company_name == "Metric AI"
    assert lead.company_url == "https://metricai.example"
    assert lead.linkedin_url == "https://linkedin.com/in/maya-founder"
    assert lead.email == "maya@metricai.example"
    assert lead.phone == "+15555550123"
    assert lead.country == "United States"
    assert lead.employee_count == 24
    assert lead.industry == "SaaS"
    assert lead.source == "apollo"
    assert lead.source_id == "64a7ff0cc4dfae00013df1a5"
    assert lead.raw_source_data["organization"]["name"] == "Metric AI"


def test_missing_apollo_key_raises_clear_error():
    with pytest.raises(ProviderAuthError, match="APOLLO_API_KEY is not configured"):
        ApolloLeadSourceProvider(settings=settings(api_key=None)).fetch_leads(10)


def test_apollo_403_raises_clear_auth_error(monkeypatch):
    response = Mock(status_code=403)
    monkeypatch.setattr("app.lead_sources.apollo_provider.httpx.post", Mock(return_value=response))

    with pytest.raises(ProviderAuthError, match="APOLLO_API_KEY, plan access, or credits"):
        ApolloLeadSourceProvider(settings=settings()).fetch_leads(10)

    assert str(APOLLO_AUTH_ERROR).startswith("Apollo API rejected")


def test_apollo_request_uses_key_header_and_icp_filters(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"people": []}
    response.raise_for_status.return_value = None
    post = Mock(return_value=response)
    monkeypatch.setattr("app.lead_sources.apollo_provider.httpx.post", post)

    ApolloLeadSourceProvider(settings=settings()).fetch_leads(75)

    assert post.call_args.args[0] == "https://apollo.test/api/v1/mixed_people/api_search"
    assert post.call_args.kwargs["headers"]["x-api-key"] == "apollo-test-key"
    assert post.call_args.kwargs["json"]["per_page"] == 75
    assert "founder" in post.call_args.kwargs["json"]["person_seniorities"]
