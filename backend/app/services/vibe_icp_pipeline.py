from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.repositories.icp_repository import icp_repository
from app.schemas.icp import LeadProfile, ScoreResult
from app.scoring.icp_engine import IcpScoringEngine
from app.scoring.vibe_score import discovery_evaluations
from app.services.vibe_prefilter import prefilter_prospect, country_name
from app.services.vibe_signals import infer_icp_signals, prepare_vibe_prospect


@dataclass(frozen=True)
class ScoredProspect:
    prospect: dict[str, Any]
    score: ScoreResult
    pipeline_status: str


@dataclass(frozen=True)
class ScoredDiscoveryBatch:
    qualified: list[ScoredProspect]
    needs_review: list[ScoredProspect]
    rejected: list[ScoredProspect]


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    if isinstance(value, str):
        cleaned = (
            value.strip()
            .replace(",", "")
            .replace("$", "")
        )

        if cleaned.isdigit():
            return int(cleaned)

    return None


def prospect_to_lead_profile(
    prospect: dict[str, Any],
) -> LeadProfile:
    company_name = str(
        prospect.get("company_name")
        or ""
    ).strip()

    if not company_name:
        company_name = "Unknown Company"

    evidence_urls: list[str] = []

    for value in prospect.get(
        "evidence_urls",
        [],
    ):
        if (
            isinstance(value, str)
            and value.strip()
        ):
            evidence_urls.append(
                value.strip()
            )

    if isinstance(prospect.get("company_url"), str):
        evidence_urls.append(prospect["company_url"])

    linkedin_url = prospect.get(
        "linkedin_url"
    )

    if (
        isinstance(linkedin_url, str)
        and linkedin_url.strip()
    ):
        evidence_urls.append(
            linkedin_url.strip()
        )

    return LeadProfile(
        company_name=company_name,
        annual_revenue=_as_int(
            prospect.get(
                "annual_revenue"
            )
            or prospect.get(
                "company_revenue"
            )
        ),
        employee_count=_as_int(
            prospect.get(
                "employee_count"
            )
            or prospect.get(
                "company_employee_count"
            )
        ),
        country=country_name(prospect.get("country")) or None,
        industry=prospect.get("industry"),
        business_model=prospect.get(
            "business_model"
        ),
        growth_stage=prospect.get(
            "growth_stage"
        ),
        buying_behavior=prospect.get(
            "buying_behavior"
        ),
        title=prospect.get("title"),
        has_funding_or_revenue=prospect.get(
            "has_funding_or_revenue"
        ),
        has_defined_software_need=prospect.get(
            "has_defined_software_need"
        ),
        has_technical_stakeholder=prospect.get(
            "has_technical_stakeholder"
        ),
        accepts_distributed_delivery=prospect.get(
            "accepts_distributed_delivery"
        ),
        evidence_urls=list(
            dict.fromkeys(
                evidence_urls
            )
        ),
    )


def _pipeline_status(
    score: ScoreResult,
) -> str:
    if score.disposition in {
        "Strong Fit",
        "Good Fit",
    }:
        return "qualified"

    if score.disposition in {
        "Review",
        "Opportunistic / Manual Review",
    }:
        return "needs_review"

    return "rejected"


def score_prospect(
    prospect: dict[str, Any],
) -> ScoredProspect:
    prospect = prepare_vibe_prospect(prospect)
    icp = icp_repository.get_active()

    engine = IcpScoringEngine(icp)

    profile = prospect_to_lead_profile(
        prospect
    )

    score = engine.score(profile)
    admission = prefilter_prospect(prospect)
    hard_stops = list(dict.fromkeys(score.hard_stops + admission.rejection_reasons))
    signals = infer_icp_signals(prospect)
    # Persist hypotheses separately from measured provider attributes. The
    # existing raw payload and evaluation JSON keep their provenance available.
    prospect = {**prospect, 'inferred_icp_signals': signals.payload()}
    evaluations = discovery_evaluations(prospect, hard_stops, signals)
    score = score.model_copy(update={
        "score": sum(item.points_awarded for item in evaluations),
        "evaluations": evaluations,
        "evidence_urls": engine._normalized_evidence_urls(
            score.evidence_urls + [item["source_url"] for item in signals.sources]
        ),
    })
    if hard_stops:
        score = score.model_copy(update={"disposition": "Disqualified", "hard_stops": hard_stops})
    elif admission.review_reasons:
        review_reasons = admission.review_reasons
        if signals.industries:
            review_reasons = [
                'Inferred ICP industry: ' + '; '.join(signals.industries),
                'Strong decision-maker fit',
            ]
            missing_size_revenue = (
                _as_int(prospect.get('employee_count')) is None
                or _as_int(prospect.get('annual_revenue')) is None
            )
            if missing_size_revenue:
                review_reasons.append('Company size/revenue missing; manual verification required')
            if signals.software_points:
                review_reasons.append('B2B/software need inferred from company/product signals')
                if missing_size_revenue and country_name(prospect.get('country')).casefold() in {
                    'united states', 'united arab emirates',
                }:
                    review_reasons.append('Strong ICP signals but company size/revenue require verification.')
            replaced = {
                'Missing company size/revenue/industry data',
                'Good decision-maker title but sparse company data',
                'Needs manual verification against Datamart ICP',
            }
            if signals.software_points:
                replaced.update({
                    'B2B business model requires verification',
                    'Software or engineering need requires verification',
                })
            review_reasons.extend(reason for reason in admission.review_reasons if reason not in replaced)
        score = score.model_copy(update={"disposition": "Review", "review_reasons": review_reasons})
    else:
        score = score.model_copy(update={"disposition": "Strong Fit" if score.score >= 80 else "Good Fit"})

    return ScoredProspect(
        prospect=prospect,
        score=score,
        pipeline_status=_pipeline_status(
            score
        ),
    )


def score_discovered_prospects(
    prospects: list[dict[str, Any]],
) -> ScoredDiscoveryBatch:
    qualified: list[ScoredProspect] = []
    needs_review: list[ScoredProspect] = []
    rejected: list[ScoredProspect] = []

    for prospect in prospects:
        result = score_prospect(
            prospect
        )

        if (
            result.pipeline_status
            == "qualified"
        ):
            qualified.append(result)

        elif (
            result.pipeline_status
            == "needs_review"
        ):
            needs_review.append(result)

        else:
            rejected.append(result)

    return ScoredDiscoveryBatch(
        qualified=qualified,
        needs_review=needs_review,
        rejected=rejected,
    )
