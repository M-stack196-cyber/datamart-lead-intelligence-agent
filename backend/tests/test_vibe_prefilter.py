from dataclasses import replace
from unittest.mock import patch

import pytest

from app.integrations.vibe.client import VibeProspectingClient
from app.services.vibe_prefilter import prefilter_prospect
from app.services.vibe_icp_pipeline import score_prospect
from app.services.vibe_discovery_persistence import persist_discovery_intelligence
from tests.test_vibe_discovery_persistence import FakeClient, intelligence_item


def prospect(**fields):
    return dict(company_name='Acme', person_name='Alex', title='CEO',
                company_url='https://acme.example', linkedin_url='https://linkedin.com/in/alex',
                country='USA', **fields)


@pytest.mark.parametrize('category', ['creator', 'media', 'education', 'newsletter',
    'university', 'school', 'influencer', 'podcast', 'non-profit', 'government',
    'publicly held', 'crypto', 'NFT', 'Web3', 'gambling', 'marketing agency',
    'design studio', 'dev shop', 'B2C'])
def test_exclusions_never_reach_ingest(category):
    row = prospect(industry=category)
    assert not prefilter_prospect(row).accepted
    assert score_prospect(row).pipeline_status == 'rejected'
    item = replace(intelligence_item(), scored_prospect=score_prospect(row))
    client = FakeClient()
    result = persist_discovery_intelligence(client, [item])
    assert not client.calls
    assert result.errors


@pytest.mark.parametrize('industry', ['SaaS', 'HealthTech', 'FinTech', 'Real Estate',
                                     'E-commerce', 'Analytics', 'IT services', 'MarTech'])
def test_target_decision_makers_with_missing_firmographics_are_reviewed(industry):
    row = prospect(industry=industry)
    assert prefilter_prospect(row).accepted
    result = score_prospect(row)
    assert result.pipeline_status == 'needs_review'
    assert result.score.review_reasons


def test_verified_software_company_is_qualified():
    row = prospect(industry='SaaS', employee_count=20, annual_revenue=2_000_000,
                   business_model='B2B SaaS', company_type='privately held')
    assert score_prospect(row).pipeline_status == 'qualified'
    row['has_defined_software_need'] = False
    assert score_prospect(row).pipeline_status == 'rejected'


@pytest.mark.parametrize('field', ['company_name', 'person_name', 'title', 'linkedin_url', 'company_url'])
def test_required_identity_fields(field):
    row = prospect()
    row[field] = ' '
    assert not prefilter_prospect(row).accepted


@pytest.mark.parametrize('url', ['https://linkedin.com/newsletters/example',
    'https://linkedin.com/in/alex', 'https://instagram.com/acme',
    'https://acme.substack.com', 'javascript:alert(1)', 'not-a-url'])
def test_weak_urls(url):
    row = prospect()
    row['company_url'] = url
    assert not prefilter_prospect(row).accepted


def test_raw_source_and_ids_reach_ingest_without_email():
    raw = dict(full_name='Alex', job_title='CEO', company_name='Acme',
               company_website='https://acme.example', linkedin='https://linkedin.com/in/alex',
               country='US', prospect_id='p1', business_id='b1', extra_provider_field='preserved')
    row = VibeProspectingClient._normalize_discovered_prospect(raw)
    item = replace(intelligence_item(), scored_prospect=score_prospect(row), business_id='b1')
    client = FakeClient()
    persist_discovery_intelligence(client, [item])
    payload = client.calls[0]['payload']['rows'][0]
    assert payload['lead_source'] == 'vibe'
    assert payload['source_captured_at']
    assert payload['vibe_prospect_id'] == 'p1'
    assert payload['vibe_business_id'] == 'b1'
    assert payload['raw_source_data'] == raw
    assert payload['person_name'] == 'Alex'
    assert payload['company_url'] == raw['company_website']
    assert 'email' not in payload


@pytest.mark.parametrize('limit', [10, 25, 50, 100])
def test_cycle_backfills_rejections_and_deduplicates_repeated_runs(limit):
    from types import SimpleNamespace
    from app.services.vibe_discovery_cycle import run_vibe_discovery_cycle
    from tests.test_vibe_discovery_persistence import RpcCall

    class StatefulClient:
        def __init__(self):
            self.rows = {}
            self.batches = []

        def rpc(self, name, payload):
            if name == 'ingest_vibe_discovered_leads':
                self.batches.append(payload['rows'])
                inserted = updated = 0
                mappings = []
                for row in payload['rows']:
                    key = row['linkedin_url']
                    if key in self.rows:
                        updated += 1
                    else:
                        inserted += 1
                        self.rows[key] = {**row, 'lead_id': str(len(self.rows))}
                    mappings.append({**self.rows[key], "duplicate": updated > 0 and inserted == 0})
                return RpcCall(dict(inserted=inserted, updated=updated, leads=mappings))
            assert name == 'persist_vibe_discovery_intelligence'
            return RpcCall(dict(evidence_count=0, evidence_ids=[]))

    good = []
    for i in range(limit):
        row = prospect(industry='SaaS')
        row.update(company_name=f'Acme {i}', company_url=f'https://acme{i}.example',
                   linkedin_url=f'https://linkedin.com/in/alex{i}', vibe_prospect_id=str(i))
        good.append(row)
    bad = prospect(industry='newsletter')
    bad['company_url'] = good[0]['company_url']
    pages = [[bad], good, good]

    def discover(client, **kwargs):
        page = kwargs['page']
        if kwargs['country_code'] == 'AE':
            return SimpleNamespace(prospects=[], total_pages=0)
        return SimpleNamespace(prospects=pages[page - 1], total_pages=len(pages))

    client = StatefulClient()
    with patch('app.services.vibe_discovery_cycle.get_settings', return_value=SimpleNamespace(
            vibe_api_key='test', vibe_api_base_url='https://example.com',
            daily_vibe_lead_limit=100, vibe_allow_over_daily_cap=False)), \
         patch('app.services.vibe_discovery_cycle.discover_from_active_icp', side_effect=discover):
        first = run_vibe_discovery_cycle(client, size=limit)
        second = run_vibe_discovery_cycle(client, size=limit)
    assert first.stored_count == limit
    assert first.rejected_count == 1
    assert first.draft_count == second.draft_count == 0
    assert second.stored_count == 0
    assert second.duplicate_count == limit * 2
    assert len(client.rows) == limit
    assert all(len(batch) <= limit for batch in client.batches)
    assert all(row.get('industry') != 'newsletter' for row in client.rows.values())


def test_cycle_searches_us_before_uae_and_stops_when_exhausted():
    from types import SimpleNamespace
    from app.services.vibe_discovery_cycle import run_vibe_discovery_cycle
    calls = []

    def discover(client, **kwargs):
        calls.append(kwargs['country_code'])
        return SimpleNamespace(prospects=[], total_pages=0)

    with patch('app.services.vibe_discovery_cycle.get_settings', return_value=SimpleNamespace(
            vibe_api_key='test', vibe_api_base_url='https://example.com',
            daily_vibe_lead_limit=100, vibe_allow_over_daily_cap=False)), \
         patch('app.services.vibe_discovery_cycle.discover_from_active_icp', side_effect=discover):
        result = run_vibe_discovery_cycle(FakeClient(), size=100)
    assert calls == ['US', 'AE']
    assert result.stored_count == 0
    assert any('Stored 0 of 100' in warning for warning in result.warnings)


def test_cycle_bounds_provider_search_when_every_row_is_rejected():
    from types import SimpleNamespace
    from app.services.vibe_discovery_cycle import run_vibe_discovery_cycle
    calls = []

    def discover(client, **kwargs):
        calls.append(kwargs)
        rows = []
        for i in range(kwargs['page_size']):
            row = prospect(industry='media')
            row['linkedin_url'] += str(len(calls)) + '-' + str(i)
            row['company_url'] = f'https://media{len(calls)}-{i}.example'
            rows.append(row)
        return SimpleNamespace(prospects=rows, total_pages=10000)

    with patch('app.services.vibe_discovery_cycle.get_settings', return_value=SimpleNamespace(
            vibe_api_key='test', vibe_api_base_url='https://example.com',
            daily_vibe_lead_limit=100, vibe_allow_over_daily_cap=False)), \
         patch('app.services.vibe_discovery_cycle.discover_from_active_icp', side_effect=discover):
        client = FakeClient()
        result = run_vibe_discovery_cycle(client, size=10)
    assert not client.calls
    assert len(calls) == 10
    assert result.fetched_count == result.rejected_count == 100
    assert [call['country_code'] for call in calls] == ['US'] * 8 + ['AE'] * 2
