from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.lead_sources.base import NormalizedLead
from app.services.vibe_icp_pipeline import ScoredProspect, score_prospect
from app.services.vibe_identity import normalized_id, normalized_name, normalized_url


@dataclass(frozen=True)
class LeadSourceIngestionResult:
    requested_count: int
    prepared_count: int
    duplicate_count: int
    qualified_count: int
    review_count: int
    rejected_count: int
    scored: list[ScoredProspect]
    warnings: list[str]
    errors: list[str]


def normalized_lead_to_prospect(lead: NormalizedLead) -> dict[str, Any]:
    prospect = {
        "person_name": lead.person_name,
        "title": lead.title,
        "company_name": lead.company_name,
        "company_url": lead.company_url,
        "linkedin_url": lead.linkedin_url,
        "email": lead.email,
        "phone": lead.phone,
        "country": lead.country,
        "employee_count": lead.employee_count,
        "industry": lead.industry,
        "lead_source": lead.source,
        "source_id": lead.source_id,
        "raw_source_data": lead.raw_source_data,
    }
    if lead.source == "apollo" and lead.source_id:
        prospect["apollo_person_id"] = lead.source_id
    return {key: value for key, value in prospect.items() if value not in (None, "")}


def dedupe_normalized_leads(leads: list[NormalizedLead]) -> tuple[list[NormalizedLead], int]:
    unique: list[NormalizedLead] = []
    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    for lead in leads:
        identities = _lead_identities(lead)
        if identities & seen:
            seen.update(identities)
            duplicates += 1
            continue
        seen.update(identities)
        unique.append(lead)
    return unique, duplicates


def prepare_and_score_leads(leads: list[NormalizedLead]) -> LeadSourceIngestionResult:
    unique, duplicates = dedupe_normalized_leads(leads)
    scored = [
        score_prospect(normalized_lead_to_prospect(lead))
        for lead in unique
    ]
    return LeadSourceIngestionResult(
        requested_count=len(leads),
        prepared_count=len(unique),
        duplicate_count=duplicates,
        qualified_count=sum(item.pipeline_status == "qualified" for item in scored),
        review_count=sum(item.pipeline_status == "needs_review" for item in scored),
        rejected_count=sum(item.pipeline_status == "rejected" for item in scored),
        scored=scored,
        warnings=[],
        errors=[],
    )


def _lead_identities(lead: NormalizedLead) -> set[tuple[str, ...]]:
    identities: set[tuple[str, ...]] = set()
    person = normalized_name(lead.person_name)
    linkedin = normalized_url(lead.linkedin_url)
    email = normalized_id(lead.email)
    source = normalized_id(lead.source)
    source_id = normalized_id(lead.source_id)
    company_url = normalized_url(lead.company_url)

    if linkedin:
        identities.add(("linkedin", linkedin))
    if email:
        identities.add(("email", email))
    if source and source_id:
        identities.add(("source", source, source_id))
    if company_url and person:
        identities.add(("website_person", company_url, person))
    return identities
