from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services.vibe_icp_pipeline import score_prospect
from app.services.vibe_discovery_persistence import persist_discovery_intelligence
from app.services.vibe_signals import infer_icp_signals
from app.workers.runner import build_enrichment_intelligence
from tests.test_vibe_prefilter import prospect
from tests.test_vibe_discovery_persistence import FakeClient, intelligence_item


@pytest.mark.parametrize('name,domain,industry,score', [
    ('OpenRouter', 'openrouter.ai', 'SaaS/AI software', 70),
    ('Taskade', 'taskade.com', 'SaaS/productivity software', 70),
    ('Atria AI', 'tryatria.com', 'SaaS/AI software', 70),
    ('Syllaby', 'syllaby.ai', 'SaaS/AI software', 70),
    ('Qubrid AI', 'qubrid.com', 'AI/cloud/software', 70),
    ('SecureStrux', 'securestrux.com', 'Cybersecurity/compliance', 60),
    ('Gaia Real Estate', 'gaiare.com', 'Real Estate / PropTech potential', 55),
    ('PocketPatientMD', 'pocketpatientmd.com', 'HealthTech', 70),
    ('Plannerly', 'plannerly.com', 'Construction/BIM software', 70),
    ('Experfy', 'experfy.com', 'Analytics/AI/talent platform', 65),
])
def test_domain_hypotheses_raise_scores_but_leave_unknown_facts_unknown(name, domain, industry, score):
    row = {**prospect(), 'company_name': name, 'company_url': 'https://' + domain}
    original = deepcopy(row)
    result = score_prospect(row)
    assert row == original
    assert result.pipeline_status == 'needs_review'
    assert result.score.score == score
    assert result.score.score == sum(item.points_awarded for item in result.score.evaluations)
    assert industry in result.prospect['inferred_icp_signals']['industries']
    assert any(reason.startswith('Inferred ICP industry:') for reason in result.score.review_reasons)
    assert 'Company size/revenue missing; manual verification required' in result.score.review_reasons
    for field in ('industry', 'employee_count', 'annual_revenue', 'business_model',
                  'company_type', 'has_defined_software_need'):
        assert result.prospect.get(field) is None
    if domain != 'gaiare.com':
        assert 'Strong ICP signals but company size/revenue require verification.' in result.score.review_reasons
    else:
        assert result.prospect['inferred_icp_signals']['software_points'] == 0


def test_nested_raw_fields_and_current_company_experience_are_attributed():
    raw = {
        'skills': [{'name': 'Software engineering'}, {'skill_name': 'Cloud infrastructure'}],
        'experience': [
            {'company_name': 'Acme', 'title': 'CTO', 'description': 'Building a healthcare software platform',
             'is_current': True},
        ],
        'company_website': 'https://acme.example',
        'company_linkedin': 'https://linkedin.com/company/acme',
        'job_level_array': ['C-suite'],
        'job_seniority_level': 'Executive',
        'job_department_array': ['Engineering'],
    }
    row = {**prospect(), 'company_url': None, 'raw_source_data': raw}
    result = score_prospect(row)
    assert result.prospect['company_url'] == raw['company_website']
    assert result.prospect['company_linkedin_url'] == raw['company_linkedin']
    assert result.prospect['raw_source_data'] == raw
    assert result.pipeline_status == 'needs_review'
    assert result.score.score == 70
    sources = result.prospect['inferred_icp_signals']['sources']
    assert any('experience[0].description' in item['field'] for item in sources)
    for key in ('skills', 'job_level_array', 'job_seniority_level', 'job_department_array'):
        assert any(item['field'].endswith(key) for item in sources)
    worker = build_enrichment_intelligence(
        {**row, 'lead_source': 'vibe', 'raw_source_data': {'raw_source_data': raw}},
        SimpleNamespace(fields={}, evidence=[]),
    )
    assert worker.score.score == result.score.score
    assert worker.score.disposition == 'Review'


@pytest.mark.parametrize('experience', [
    [{'company_name': 'Previous Company', 'description': 'Built AI software', 'is_current': False}],
    [{'company_name': 'Acme', 'description': 'Built AI software', 'end_date': '2020-01-01'}],
    [{'description': 'Software developer at an unidentified employer'}],
    'Previously worked at an AI company',
])
def test_previous_or_unattributed_experience_does_not_infer_current_company(experience):
    result = score_prospect(prospect(raw_source_data={'experience': experience, 'skills': ['Python', 'Software']}))
    assert result.score.score == 40
    assert not result.prospect['inferred_icp_signals']['industries']


def test_technical_role_and_skills_support_only_moderate_inference():
    row = {**prospect(), 'title': 'CTO', 'raw_source_data': {
        'skills': ['FinTech', 'Software engineering'], 'job_department_array': ['Engineering'],
    }}
    result = score_prospect(row)
    assert result.score.score == 60
    assert result.pipeline_status == 'needs_review'
    assert 'FinTech/financial software' in result.prospect['inferred_icp_signals']['industries']


@pytest.mark.parametrize('url', ['https://openrouter.ai.evil.example', 'https://unknown.ai',
                                'https://example.com/openrouter.ai'])
def test_domain_hints_do_not_match_suffix_spoofs_or_ai_tld_alone(url):
    result = score_prospect({**prospect(), 'company_url': url})
    assert result.score.score == 40


@pytest.mark.parametrize('name,url', [
    ('Simon Sinek', 'simonsinek.com'), ('The Futur', 'thefutur.com'),
    ('Poets and Quants', 'poetsandquants.com'),
    ('Human Workplace', 'linkedin.com/newsletters/human-workplace'),
    ('Technical Institute', 'institute.example'), ('AlgoExpert', 'algoexpert.example'),
    ('Analyst Builder', 'analystbuilder.example'), ('Shay Rowbottom Marketing', 'shay.example'),
])
def test_excluded_companies_remain_zero_even_with_strong_nested_signals(name, url):
    row = {**prospect(), 'company_name': name, 'company_url': url,
           'raw_source_data': {'skills': ['SaaS', 'AI'], 'company_description': 'B2B software platform'}}
    result = score_prospect(row)
    assert result.pipeline_status == 'rejected'
    assert result.score.hard_stops
    assert result.score.score == 0


@pytest.mark.parametrize('changes', [
    {'country': 'Canada'}, {'annual_revenue': 100_000}, {'employee_count': 500},
    {'has_defined_software_need': False}, {'business_model': 'marketing agency'},
    {'company_url': 'linkedin.com/newsletters/openrouter'},
])
def test_known_domain_never_overrides_existing_hard_stops(changes):
    row = {**prospect(), 'company_name': 'OpenRouter', 'company_url': 'https://openrouter.ai', **changes}
    result = score_prospect(row)
    assert result.pipeline_status == 'rejected'
    assert result.score.score == 0


def test_inferences_are_stored_separately_and_do_not_generate_drafts():
    base = intelligence_item()
    row = {**base.scored_prospect.prospect, 'company_url': 'https://taskade.com', 'company_name': 'Taskade'}
    for field in ('employee_count', 'annual_revenue', 'industry', 'business_model', 'company_type', 'has_defined_software_need'):
        row.pop(field, None)
    client = FakeClient()
    result = persist_discovery_intelligence(client, [replace(base, scored_prospect=score_prospect(row))])
    payload = client.calls[0]['payload']['rows'][0]
    assert payload['inferred_icp_signals']['inferred'] is True
    assert payload['inferred_icp_signals']['sources']
    assert result.draft_count == 0
    assert all('draft' not in call['name'] for call in client.calls)


def test_raw_input_types_are_bounded_and_ignored_when_unusable():
    row = prospect(raw_source_data={'skills': None, 'experience': [None, 12, {}],
                                   'job_level_array': {'unknown': 'AI'}, 'company_description': 123})
    assert infer_icp_signals(row).industries == []


@pytest.mark.parametrize('context,category', [
    ({'title': 'Founder of a HealthTech software company'}, 'HealthTech'),
    ({'company_name': 'Acme Analytics'}, 'Analytics/MarTech/data platforms'),
    ({'raw_source_data': {'company_description': 'Financial software platform for B2B payments'}}, 'FinTech/financial software'),
    ({'raw_source_data': {'company_description': 'An e-commerce platform for DTC brands'}}, 'E-commerce/DTC'),
    ({'raw_source_data': {'company_description': 'Building information modeling workflow software'}}, 'Construction/BIM software'),
])
def test_generic_context_inference_does_not_depend_on_named_domain_hints(context, category):
    result = score_prospect({**prospect(), **context})
    assert category in result.prospect['inferred_icp_signals']['industries']
    assert result.score.score > 40
    assert result.pipeline_status == 'needs_review'


def test_nested_description_exclusion_still_blocks_inference():
    row = prospect(raw_source_data={'description': 'Marketing agency offering an AI platform'})
    result = score_prospect(row)
    assert result.score.score == 0
    assert result.pipeline_status == 'rejected'


def test_bare_provider_domain_has_direct_hypothesis_source_link():
    result = score_prospect({**prospect(), 'company_url': 'taskade.com'})
    assert result.prospect['company_url'] == 'taskade.com'
    assert 'https://taskade.com' in result.score.evidence_urls
    assert all(item['source_url'] == 'https://taskade.com'
               for item in result.prospect['inferred_icp_signals']['sources'])
