"""Run with VIBE_TEST_PG_SOCKET=/tmp/<isolated postgres socket directory>.

Creates/drops only its own random test database. Never accepts a remote DSN.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from app.services.vibe_identity import normalized_name, normalized_url


@pytest.fixture(scope='module')
def database():
    socket = os.environ.get('VIBE_TEST_PG_SOCKET')
    if not socket:
        pytest.skip('Set VIBE_TEST_PG_SOCKET to run real PostgreSQL ingest tests')
    assert Path(socket).resolve().is_relative_to('/tmp'), 'Use an isolated /tmp PostgreSQL server'
    params = dict(host=socket, port=55439, autocommit=True)
    name = 'vibe_test_' + uuid4().hex
    with psycopg.connect(dbname='postgres', **params) as admin:
        for role in ('anon', 'authenticated', 'service_role'):
            if not admin.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                admin.execute(sql.SQL('create role {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL("create database {} template template0 encoding 'UTF8' lc_collate 'C.UTF-8' lc_ctype 'C.UTF-8'").format(sql.Identifier(name)))
    try:
        with psycopg.connect(dbname=name, **params) as conn:
            conn.execute((Path(__file__).parent / 'fixtures/vibe_ingest_schema.sql').read_text())
            conn.execute((Path(__file__).parents[2] / 'supabase/migrations/20260909112152_tighten_vibe_person_identity.sql').read_text())
        yield dict(dbname=name, **params)
    finally:
        with psycopg.connect(dbname='postgres', **params) as admin:
            admin.execute(sql.SQL('drop database {}').format(sql.Identifier(name)))


@pytest.fixture
def db(database):
    with psycopg.connect(**database) as conn:
        conn.execute('truncate public.leads, public.imports, public.audit_log')
        conn.execute("set request.jwt.claim.role = 'service_role'")
        yield conn


def row(i=0):
    return dict(company_name=f'Acme {i}', person_name='Alex Morgan', title='CEO',
                company_url=f'https://acme{i}.example', linkedin_url=f'https://linkedin.com/in/alex{i}',
                vibe_prospect_id=f'p{i}', vibe_business_id=f'b{i}', country='USA',
                raw_source_data={'original': 'preserved'})


def ingest(conn, rows):
    return conn.execute('select public.ingest_vibe_discovered_leads(%s)', (Jsonb(rows),)).fetchone()[0]


@pytest.mark.parametrize('key', ['prospect', 'business_person', 'linkedin', 'website_person', 'company_person'])
def test_each_identity_blocks_repeat_insert(db, key):
    original = row()
    assert ingest(db, [original])['inserted'] == 1
    candidate = row(1)
    candidate.update({
        'prospect': {'vibe_prospect_id': ' P0 '},
        'business_person': {'vibe_business_id': ' B0 ', 'person_name': ' ALEX   MORGAN '},
        'linkedin': {'linkedin_url': 'http://www.linkedin.com/in/ALEX0/?trk=1#bio'},
        'website_person': {'company_url': 'http://www.acme0.example/?utm=1', 'person_name': 'ALEX  MORGAN'},
        'company_person': {'company_name': '  ACME 0!!! ', 'person_name': ' ALEX MORGAN '},
    }[key])
    result = ingest(db, [candidate])
    assert result['inserted'] == 0
    assert result['duplicates'] == 1
    assert result['leads'][0]['duplicate'] is True
    assert db.execute('select count(*) from public.leads').fetchone()[0] == 1


@pytest.mark.parametrize('limit', [10, 25, 50, 100])
def test_daily_limits_repeat_without_new_rows(db, limit):
    rows = [row(i) for i in range(limit)]
    assert ingest(db, rows)['inserted'] == limit
    result = ingest(db, rows)
    assert result['duplicates'] == limit
    assert result['inserted'] == 0
    assert db.execute('select count(*) from public.leads').fetchone()[0] == limit


def test_two_decision_makers_at_one_business_are_distinct(db):
    original = row()
    other = {**original, 'person_name': 'Taylor', 'vibe_prospect_id': 'p2',
             'linkedin_url': 'linkedin.com/in/taylor'}
    assert ingest(db, [original, other])['inserted'] == 2


def test_concurrent_runs_are_serialized(database, db):
    def run():
        with psycopg.connect(**database) as conn:
            conn.execute("set request.jwt.claim.role = 'service_role'")
            return ingest(conn, [row()])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(result['inserted'] for result in results) == 1
    assert sum(result['duplicates'] for result in results) == 1
    assert db.execute('select count(*) from public.leads').fetchone()[0] == 1


@pytest.mark.parametrize('value', ['HTTP://WWW.Acme.example/Path/?q=1#x',
                                  'linkedin.com/in/alex/', 'https://acme.example/%70ath',
                                  '', None])
def test_python_sql_url_normalization_agree(db, value):
    assert db.execute('select private.vibe_normalized_url(%s)', (value,)).fetchone()[0] == normalized_url(value)


def test_name_normalization_and_source_mapping(db):
    assert db.execute("select private.vibe_normalized_name('  Alex---Morgan! ')").fetchone()[0] == normalized_name('  Alex---Morgan! ')
    ingest(db, [row()])
    record = db.execute('select lead_source, source_captured_at, vibe_prospect_id, vibe_business_id, raw_source_data from public.leads').fetchone()
    assert record[0] == 'vibe'
    assert record[1] is not None
    assert record[2:4] == ('p0', 'b0')
    assert record[4]['raw_source_data'] == {'original': 'preserved'}


def test_rpc_and_helper_permissions_fail_closed(db):
    for role in ('anon', 'authenticated'):
        assert not db.execute("select has_function_privilege(%s, 'public.ingest_vibe_discovered_leads(jsonb)', 'EXECUTE')", (role,)).fetchone()[0]
    assert db.execute("select has_function_privilege('service_role', 'public.ingest_vibe_discovered_leads(jsonb)', 'EXECUTE')").fetchone()[0]
    db.execute("set request.jwt.claim.role = ''")
    with pytest.raises(psycopg.errors.RaiseException, match='Service role required'):
        ingest(db, [row()])


def test_missing_required_fields_never_inserted(db):
    result = ingest(db, [{'vibe_prospect_id': 'id-only'}])
    assert result['rejected'] == 1
    assert result['inserted'] == 0
