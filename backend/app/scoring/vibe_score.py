"""Explainable discovery scoring; excluded rows never earn fit points."""
from typing import Any

from app.schemas.icp import RuleEvaluation
from app.services.vibe_signals import InferredIcpSignals, infer_icp_signals, prepare_vibe_prospect
from app.services.vibe_prefilter import (
    INDUSTRIES, TITLES, country_name, matches, weak_company_url,
)


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(',', '').replace('$', ''))
        return number if 0 <= number < float('inf') else None
    except (ValueError, TypeError):
        return None


def discovery_evaluations(
    prospect: dict[str, Any], hard_stops: list[str], signals: InferredIcpSignals | None = None,
) -> list[RuleEvaluation]:
    prospect = prepare_vibe_prospect(prospect)
    signals = signals or infer_icp_signals(prospect)
    company_signals = ' '.join(str(prospect.get(key) or '') for key in (
        'industry', 'business_model', 'company_description', 'description',
    ))
    employees = numeric_value(prospect.get('employee_count'))
    revenue = numeric_value(prospect.get('annual_revenue'))
    checks = [
        ('decision_maker_fit', 'Decision-maker title', 15, bool(prospect.get('title')),
         matches(prospect.get('title'), TITLES)),
        ('geography_fit', 'USA/UAE company geography', 15, bool(prospect.get('country')),
         country_name(prospect.get('country')).casefold() in {'united states', 'united arab emirates'}),
        ('website_quality', 'Independent company URL passes exclusion checks', 10,
         bool(prospect.get('company_url')), not weak_company_url(prospect.get('company_url'))),
        ('industry_fit', 'Documented ICP vertical/product signals', 20, bool(company_signals.strip()),
         matches(company_signals, INDUSTRIES + ['B2B product', 'software product'])),
        ('business_model_fit', 'Explicit B2B company signals', 10, bool(company_signals.strip()),
         matches(company_signals, ['B2B', 'business-to-business'])),
        ('employee_fit', 'Company size 1–50', 10, employees is not None,
         employees is not None and 1 <= employees <= 50),
        ('revenue_fit', 'Revenue $500K–$20M', 10, revenue is not None,
         revenue is not None and 500_000 <= revenue <= 20_000_000),
        ('private_ownership', 'Private company ownership', 5, bool(prospect.get('company_type')),
         matches(prospect.get('company_type'), ['private', 'privately held'])),
        ('software_need', 'Defined software/engineering need', 5,
         prospect.get('has_defined_software_need') is not None,
         prospect.get('has_defined_software_need') is True),
    ]
    evaluations = []
    for key, label, weight, known, matched in checks:
        outcome = 'matched' if matched else ('failed' if known else 'unknown')
        explanation = (
            'Supported by supplied prospect attributes; website content has not been independently verified.'
            if matched else 'No supporting prospect data.' if not known else 'Does not meet this criterion.'
        )
        if hard_stops:
            outcome = 'failed'
            explanation = 'No fit points awarded: deterministic hard-stop exclusions apply.'
        awarded = weight if matched and not hard_stops else 0
        inferred_points = {
            'industry_fit': signals.industry_points,
            'business_model_fit': signals.software_points,
        }.get(key, 0)
        if inferred_points and not hard_stops and not matched:
            awarded = min(weight, inferred_points)
            outcome = 'matched'
            explanation = (
                'Inferred ICP industry/product fit: ' if key == 'industry_fit'
                else 'B2B/software need inferred from company/product signals: '
            ) + '; '.join(signals.industries)
            explanation += '. Hypothesis only; not a verified company fact. Sources: ' + ', '.join(
                dict.fromkeys(item['field'] for item in signals.sources)
            )
        evaluations.append(RuleEvaluation(
            rule_key=key, label=label, outcome=outcome,
            points_awarded=awarded,
            points_available=weight, explanation=explanation,
        ))
    return evaluations
