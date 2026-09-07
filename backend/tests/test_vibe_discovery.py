from unittest.mock import Mock, patch

from app.integrations.vibe.client import VibeDiscoveryResult
from app.integrations.vibe.client import VibeProspectingClient
from app.repositories.icp_repository import icp_repository
from app.services.vibe_discovery import (
    build_vibe_filters,
    discover_from_active_icp,
)


class FakeVibeClient:
    def __init__(self):
        self.calls = []

    def discover(
        self,
        *,
        filters,
        size,
        page_size,
        page,
    ):
        self.calls.append(
            {
                "filters": filters,
                "size": size,
                "page_size": page_size,
                "page": page,
            }
        )

        return VibeDiscoveryResult(
            prospects=[
                {
                    "person_name": "Test Lead",
                    "company_name": "Test Company",
                    "title": "CEO",
                    "country": "United States",
                    "linkedin_url": "linkedin.com/in/test",
                }
            ],
            total_results=1,
            page=1,
            total_pages=1,
            raw_result={},
        )


def test_active_icp_maps_to_vibe_filters():
    icp = icp_repository.get_active()

    filters = build_vibe_filters(icp)

    assert filters["company_country_code"]["values"] == [
        "US",
        "AE",
    ]

    assert filters["company_size"]["values"] == [
        "1-10",
        "11-50",
    ]

    assert filters["company_revenue"]["values"] == [
        "0-500K",
        "500K-1M",
        "1M-5M",
        "5M-10M",
        "10M-25M",
    ]

    assert "CEO" in filters["job_title"]["values"]
    assert "CTO" in filters["job_title"]["values"]
    assert filters["has_email"]["value"] is True


def test_discovery_uses_active_icp():
    client = FakeVibeClient()

    result = discover_from_active_icp(
        client,
        size=10,
        page_size=10,
        page=1,
    )

    assert result.icp_id == "datamart-icp-v2"
    assert result.icp_version == 2
    assert result.total_results == 1
    assert len(result.prospects) == 1

    assert len(client.calls) == 1
    assert (
        client.calls[0]["filters"]
        == result.filters
    )


@patch("app.integrations.vibe.client.httpx.post")
def test_discovery_normalizes_provider_ids_company_website_and_evidence(mock_post):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [
            {
                "prospect_id": "prospect-1",
                "business_id": "business-1",
                "full_name": "Avery Chen",
                "company_name": "Northstar Labs",
                "company_website": "https://northstar.example",
                "email": "avery@northstar.example",
                "evidence": [
                    {
                        "title": "Northstar is hiring data engineers",
                        "source_url": "https://northstar.example/jobs/data-engineer",
                        "evidence_type": "job_page",
                        "publisher": "Northstar Labs",
                        "excerpt": "The company is expanding its data platform team.",
                        "supports_fields": ["hiring", "intent"],
                    }
                ],
            }
        ],
        "total_results": 1,
        "page": 1,
        "total_pages": 1,
    }
    mock_post.return_value = response

    result = VibeProspectingClient("test-key").discover(
        filters={}, size=10, page_size=10, page=1
    )

    prospect = result.prospects[0]
    assert prospect["vibe_prospect_id"] == "prospect-1"
    assert prospect["vibe_business_id"] == "business-1"
    assert prospect["company_url"] == "https://northstar.example"
    assert prospect["evidence"][0]["source_url"].startswith("https://")
