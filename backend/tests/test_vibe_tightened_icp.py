from dataclasses import replace

import pytest

from app.services.vibe_identity import prospect_identities
from app.services.vibe_icp_pipeline import score_prospect
from app.services.vibe_discovery_persistence import persist_discovery_intelligence
from tests.test_vibe_prefilter import prospect
from tests.test_vibe_discovery_persistence import FakeClient, intelligence_item, RpcCall


@pytest.mark.parametrize('name,url,title', [
    ('Simon Sinek', 'simonsinek.com', 'Founder and visionary'),
    ('The Futur', 'thefutur.com', 'Founder CEO'),
    ('Poets and Quants', 'poetsandquants.com', 'editor-in-chief'),
    ('Human Workplace', 'linkedin.com/newsletters/human-workplace-123', 'Founder'),
    ('Technical Institute of America', 'tia.example', 'CEO'),
    ('Analyst Builder', 'analystbuilder.example', 'Founder'),
    ('AlgoExpert', 'algoexpert.example', 'CEO'),
    ('Shay Rowbottom Marketing', 'shay.example', 'Founder'),
    ('Chris Do', 'chris.example', 'CEO'),
    ('DisruptHR', 'disrupt.example', 'CEO'),
])
def test_production_examples_rejected_before_save(name, url, title):
    row = {**prospect(), 'company_name': name, 'company_url': url, 'title': title}
    scored = score_prospect(row)
    assert scored.pipeline_status == 'rejected'
    assert scored.score.score == 0
    assert scored.score.hard_stops
    client = FakeClient()
    result = persist_discovery_intelligence(client, [replace(intelligence_item(), scored_prospect=scored)])
    assert result.errors
    assert client.calls == []


@pytest.mark.parametrize('field,value', [
    ('company_url', 'https://beacons.ai/company'),
    ('company_url', 'https://www.linkedin.com/%6Eewsletters/example'),
    ('company_url', 'https://courses.example.com'),
    ('company_url', 'https://acmetraining.example'),
    ('company_url', 'https://redirect.example/?url=https://medium.com/alex'),
    ('company_description', 'An online courses business for aspiring analysts'),
    ('company_url', 'https://acme.example/course/founder'),
    ('company_name', 'Acme Academy'),
    ('company_name', 'Acme Community'),
    ('title', 'Founder / Keynote Speaker'),
    ('title', 'CEO and Author'),
    ('business_model', 'Personal branding agency'),
])
def test_exclusions_override_all_positive_company_attributes(field, value):
    row = {**intelligence_item().scored_prospect.prospect, field: value}
    assert score_prospect(row).pipeline_status == 'rejected'


@pytest.mark.parametrize('name,url,title', [
    ('RepVue', 'repvue.com', 'Founder CEO'),
    ('Thinking Machines Lab', 'thinkingmachines.example', 'Co-founder CEO'),
])
def test_sparse_company_examples_get_explicit_review_reasons(name, url, title):
    row = {**prospect(), 'company_name': name, 'company_url': url, 'title': title}
    result = score_prospect(row)
    assert result.pipeline_status == 'needs_review'
    assert set(result.score.review_reasons) >= {
        'Missing company size/revenue/industry data',
        'Good decision-maker title but sparse company data',
        'Needs manual verification against Datamart ICP',
    }


@pytest.mark.parametrize('country', ['Canada', 'United Kingdom', 'India', 'Antarctica'])
def test_outside_geo_cannot_be_promoted_by_provider_flags(country):
    row = {**prospect(industry='SaaS'), 'country': country,
           'opportunistic_reason': 'Provider says this is a great founder', 'opportunistic': True}
    result = score_prospect(row)
    assert result.pipeline_status == 'rejected'
    assert 'Outside USA/UAE geography' in result.score.hard_stops


def test_scores_reflect_company_signals_not_just_founder_title():
    sparse = score_prospect(prospect()).score
    saas = score_prospect(prospect(industry='SaaS')).score
    b2b = score_prospect(prospect(industry='SaaS', business_model='B2B')).score
    excluded = score_prospect(prospect(industry='Education')).score
    assert 0 == excluded.score < sparse.score < saas.score < b2b.score
    for result in [sparse, saas, b2b, excluded]:
        assert result.score == sum(rule.points_awarded for rule in result.evaluations)


@pytest.mark.parametrize('industry,country', [('SaaS', 'USA'), ('HealthTech', 'UAE')])
def test_verified_target_company_qualifies(industry, country):
    row = {**intelligence_item().scored_prospect.prospect, 'industry': industry, 'country': country}
    result = score_prospect(row)
    assert result.pipeline_status == 'qualified'
    assert result.score.score >= 80


@pytest.mark.parametrize('changes', [
    {'vibe_prospect_id': ' P1 ', 'company_name': 'Different', 'person_name': 'Different', 'linkedin_url': 'linkedin.com/in/other', 'company_url': 'other.example'},
    {'vibe_prospect_id': 'p2', 'linkedin_url': 'linkedin.com/in/other', 'company_url': 'other.example', 'company_name': 'Other'},
    {'vibe_prospect_id': 'p2', 'vibe_business_id': 'b2', 'linkedin_url': 'HTTP://WWW.LINKEDIN.COM/in/Alex/?trk=x#bio'},
    {'vibe_prospect_id': 'p2', 'vibe_business_id': 'b2', 'linkedin_url': 'linkedin.com/in/other', 'company_url': 'http://www.acme.example/?utm=x', 'company_name': 'Other'},
    {'vibe_prospect_id': 'p2', 'vibe_business_id': 'b2', 'linkedin_url': 'linkedin.com/in/other', 'company_url': 'other.example', 'company_name': '  ACME!!! ', 'person_name': '  ALEX  '},
])
def test_requested_identity_keys_find_duplicates(changes):
    base = prospect(vibe_prospect_id='p1', vibe_business_id='b1')
    assert prospect_identities(base) & prospect_identities({**base, **changes})


def test_two_people_at_same_company_are_not_duplicates():
    base = prospect(vibe_prospect_id='p1', vibe_business_id='b1')
    other = {**base, 'person_name': 'Other', 'vibe_prospect_id': 'p2', 'linkedin_url': 'linkedin.com/in/other'}
    assert not prospect_identities(base) & prospect_identities(other)


def test_duplicate_items_only_persist_and_draft_once():
    client = FakeClient()
    item = intelligence_item()
    result = persist_discovery_intelligence(client, [item, item])
    assert result.duplicate_count == 1
    assert len(client.calls[0]['payload']['rows']) == 1
    assert len(result.leads) == result.draft_count == 1


def test_database_duplicate_does_not_reappear_or_get_drafted():
    class DuplicateClient(FakeClient):
        def rpc(self, name, payload):
            assert name == 'ingest_vibe_discovered_leads'
            return RpcCall({'duplicates': 1, 'inserted': 0, 'leads': [
                {**payload['rows'][0], 'lead_id': 'existing', 'duplicate': True},
            ]})
    result = persist_discovery_intelligence(DuplicateClient(), [intelligence_item()])
    assert result.duplicate_count == 1
    assert result.leads == []
    assert result.draft_count == result.evidence_count == 0


def test_worker_reprocessing_preserves_vibe_exclusions_and_review_reasons():
    from types import SimpleNamespace
    from app.workers.runner import build_enrichment_intelligence
    enrichment = SimpleNamespace(fields={}, evidence=[])
    lead = {**prospect(), 'lead_source': 'vibe', 'company_name': 'Simon Sinek',
            'company_url': 'simonsinek.com'}
    result = build_enrichment_intelligence(lead, enrichment)
    assert result.score.disposition == 'Disqualified'
    assert result.score.score == 0
    sparse = build_enrichment_intelligence({**prospect(), 'lead_source': 'vibe'}, enrichment)
    assert 'Needs manual verification against Datamart ICP' in sparse.score.review_reasons
