from collections.abc import Callable
import re
from urllib.parse import urlparse

from app.schemas.icp import IcpDefinition, LeadProfile, RuleEvaluation, ScoreResult


def _normal(value: str | None) -> str:
    return (value or "").strip().casefold()


def _contains(value: str | None, options: list[str]) -> bool:
    candidate = _normal(value)
    return bool(candidate) and any(
        re.search(rf"(?<!\w){re.escape(_normal(option))}(?!\w)", candidate)
        for option in options
    )


class IcpScoringEngine:
    def __init__(self, definition: IcpDefinition) -> None:
        self.definition = definition

    @staticmethod
    def _normalized_evidence_urls(urls: list[str] | None) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in urls or []:
            if not isinstance(raw, str):
                continue
            candidate = raw.strip()
            if not candidate:
                continue
            parsed = urlparse(candidate)
            if parsed.scheme.lower() not in {"http", "https"}:
                continue
            if not parsed.netloc:
                continue
            cleaned = candidate.split("#", 1)[0].rstrip("/")
            if cleaned.lower() in seen:
                continue
            seen.add(cleaned.lower())
            normalized.append(cleaned)
        return normalized

    def score(self, lead: LeadProfile) -> ScoreResult:
        hard_stops = self._hard_stops(lead)
        review_reasons = self._review_reasons(lead)
        evidence_urls = self._normalized_evidence_urls(lead.evidence_urls)
        checks: dict[str, tuple[object, Callable[[], bool], str, str]] = {
            "revenue_fit": (
                lead.annual_revenue,
                lambda: self.definition.revenue_min <= (lead.annual_revenue or 0) <= self.definition.revenue_max,
                "Revenue is within the $500K-$20M ICP range.",
                "Revenue is outside the target range.",
            ),
            "employee_fit": (
                lead.employee_count,
                lambda: self.definition.employee_min <= (lead.employee_count or 0) <= self.definition.employee_max,
                "Headcount is within the 1-50 employee range.",
                "Headcount is outside the primary ICP range.",
            ),
            "industry_fit": (
                lead.industry,
                lambda: _contains(lead.industry, self.definition.target_industries),
                "Industry matches a priority Datamart vertical.",
                "Industry is not a documented priority vertical.",
            ),
            "geography_fit": (
                lead.country,
                lambda: _contains(lead.country, self.definition.target_countries),
                "Headquarters is inside the US/UAE focus.",
                "Headquarters is outside the approved focus.",
            ),
            "growth_fit": (
                lead.growth_stage,
                lambda: _contains(lead.growth_stage, self.definition.accepted_growth_stages),
                "Growth stage indicates a product, revenue, or funding foundation.",
                "Growth stage does not show post-idea readiness.",
            ),
            "business_model_fit": (
                lead.business_model,
                lambda: _contains(lead.business_model, self.definition.accepted_business_models),
                "Business model matches the ICP.",
                "Business model is not in the approved set.",
            ),
            "decision_maker_fit": (
                lead.title,
                lambda: _contains(lead.title, self.definition.decision_maker_titles),
                "Contact title matches an accessible decision maker.",
                "Contact title does not match a target decision maker.",
            ),
            "buying_readiness": (
                lead.buying_behavior,
                lambda: _contains(lead.buying_behavior, self.definition.accepted_buying_behaviors),
                "Buying behavior supports a retainer or milestone SOW.",
                "Buying behavior does not yet show structured engagement readiness.",
            ),
        }

        evaluations: list[RuleEvaluation] = []
        total = 0
        for rule in self.definition.scoring_rules:
            raw_value, predicate, success, failure = checks[rule.key]
            if raw_value is None:
                outcome = "unknown"
                points = 0
                explanation = "No reliable evidence is available for this criterion."
            elif predicate():
                outcome = "matched"
                points = rule.weight
                explanation = success
            else:
                outcome = "failed"
                points = 0
                explanation = failure
            total += points
            evaluations.append(
                RuleEvaluation(
                    rule_key=rule.key,
                    label=rule.label,
                    outcome=outcome,
                    points_awarded=points,
                    points_available=rule.weight,
                    explanation=explanation,
                )
            )

        disposition = self._disposition(total, hard_stops, review_reasons)
        return ScoreResult(
            company_name=lead.company_name,
            icp_id=self.definition.id,
            icp_version=self.definition.version,
            score=total,
            disposition=disposition,
            tier=self._tier(lead),
            persona=self._persona(lead.title),
            hard_stops=hard_stops,
            review_reasons=review_reasons,
            evaluations=evaluations,
            evidence_urls=evidence_urls,
        )

    def _hard_stops(self, lead: LeadProfile) -> list[str]:
        stops: list[str] = []
        if lead.annual_revenue is not None and lead.annual_revenue < self.definition.revenue_min:
            stops.append("Annual revenue is below $500K.")
        if _contains(lead.business_model, self.definition.excluded_business_models):
            stops.append("Business model is explicitly excluded.")
        if lead.has_defined_software_need is False:
            stops.append("No defined software need exists.")
        if lead.accepts_distributed_delivery is False:
            stops.append("Prospect requires an on-site delivery model.")
        return stops

    def _review_reasons(self, lead: LeadProfile) -> list[str]:
        if lead.country is not None and not _contains(
            lead.country, self.definition.target_countries
        ):
            return [
                "Headquarters is outside the USA/UAE focus; treat as opportunistic and review manually."
            ]
        return []

    @staticmethod
    def _disposition(score: int, hard_stops: list[str], review_reasons: list[str]) -> str:
        if hard_stops:
            return "Disqualified"
        if review_reasons:
            return "Opportunistic / Manual Review"
        if score >= 80:
            return "Strong Fit"
        if score >= 65:
            return "Good Fit"
        if score >= 45:
            return "Review"
        return "Not Qualified"

    def _tier(self, lead: LeadProfile) -> str:
        if lead.annual_revenue is None or lead.employee_count is None:
            return "Unassigned"
        for tier in self.definition.tiers:
            if tier.revenue_min <= lead.annual_revenue <= tier.revenue_max and tier.employees_min <= lead.employee_count <= tier.employees_max:
                return tier.name
        return "Unassigned"

    def _persona(self, title: str | None) -> str | None:
        for persona in self.definition.personas:
            if _contains(title, persona.titles):
                return persona.name
        return None
