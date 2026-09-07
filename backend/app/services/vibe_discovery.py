from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.vibe.client import (
    VibeDiscoveryResult,
    VibeProspectingClient,
)
from app.repositories.icp_repository import icp_repository
from app.schemas.icp import IcpDefinition


COUNTRY_CODE_MAP = {
    "united states": "US",
    "usa": "US",
    "united arab emirates": "AE",
    "uae": "AE",
}


@dataclass(frozen=True)
class DiscoveryBatch:
    icp_id: str
    icp_version: int
    filters: dict[str, Any]
    prospects: list[dict[str, Any]]
    total_results: int
    page: int
    total_pages: int


def _country_codes(icp: IcpDefinition) -> list[str]:
    codes: list[str] = []

    for country in icp.target_countries:
        code = COUNTRY_CODE_MAP.get(
            country.strip().casefold()
        )

        if code and code not in codes:
            codes.append(code)

    return codes


def _company_size_buckets(
    minimum: int,
    maximum: int,
) -> list[str]:
    buckets = [
        (1, 10, "1-10"),
        (11, 50, "11-50"),
        (51, 200, "51-200"),
        (201, 500, "201-500"),
        (501, 1000, "501-1000"),
        (1001, 5000, "1001-5000"),
        (5001, 10000, "5001-10000"),
        (10001, 10**12, "10001+"),
    ]

    return [
        label
        for low, high, label in buckets
        if high >= minimum and low <= maximum
    ]


def _revenue_buckets(
    minimum: int,
    maximum: int,
) -> list[str]:
    buckets = [
        (0, 500_000, "0-500K"),
        (500_000, 1_000_000, "500K-1M"),
        (1_000_000, 5_000_000, "1M-5M"),
        (5_000_000, 10_000_000, "5M-10M"),
        (10_000_000, 25_000_000, "10M-25M"),
        (25_000_000, 75_000_000, "25M-75M"),
        (75_000_000, 200_000_000, "75M-200M"),
        (200_000_000, 500_000_000, "200M-500M"),
        (500_000_000, 1_000_000_000, "500M-1B"),
        (1_000_000_000, 10_000_000_000, "1B-10B"),
    ]

    return [
        label
        for low, high, label in buckets
        if high >= minimum and low <= maximum
    ]


def build_vibe_filters(
    icp: IcpDefinition,
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "has_email": {
            "value": True,
        },
        "job_title": {
            "values": list(
                dict.fromkeys(
                    icp.decision_maker_titles
                )
            ),
            "include_related_job_titles": True,
        },
    }

    country_codes = _country_codes(icp)

    if country_codes:
        filters["company_country_code"] = {
            "values": country_codes,
        }

    company_sizes = _company_size_buckets(
        icp.employee_min,
        icp.employee_max,
    )

    if company_sizes:
        filters["company_size"] = {
            "values": company_sizes,
        }

    revenue_ranges = _revenue_buckets(
        icp.revenue_min,
        icp.revenue_max,
    )

    if revenue_ranges:
        filters["company_revenue"] = {
            "values": revenue_ranges,
        }

    return filters


def discover_from_active_icp(
    client: VibeProspectingClient,
    *,
    size: int = 25,
    page_size: int = 25,
    page: int = 1,
) -> DiscoveryBatch:
    icp = icp_repository.get_active()

    filters = build_vibe_filters(icp)

    result: VibeDiscoveryResult = client.discover(
        filters=filters,
        size=size,
        page_size=page_size,
        page=page,
    )

    return DiscoveryBatch(
        icp_id=icp.id,
        icp_version=icp.version,
        filters=filters,
        prospects=result.prospects,
        total_results=result.total_results,
        page=result.page,
        total_pages=result.total_pages,
    )
