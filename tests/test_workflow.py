"""Explicit test fixtures only; these are never imported into the operator's database."""
import hashlib
import io
import json
import os
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app import workflow_models as m
from app.auth import verified_identity
from app.database import tenant_session
from app.extraction import extract, archive_members
from app.main import app
from app.workflow import insert


def test_period_and_unassessed_validation():
    valid = dict(exact_text='TEST FIXTURE: this is a documentary assertion.', period_from='2024-01-01',
                 period_to='2024-12-31', jurisdictions=['PT'], scope_note='TEST FIXTURE scope only', claim_type='documentary')
    assert m.Claim(**valid).status == 'UNASSESSED'
    for changes in [dict(period_from='2025-01-01'), dict(status='SUPPORTED'), dict(exact_text=''), dict(period_to=None)]:
        with pytest.raises(ValidationError):
            m.Claim(**(valid | changes))


def test_extract_json_preserves_decimal_lexical_text():
    raw = b'{"value":123456789.0123456789,"missing":null}'
    parsed = extract(raw)
    assert parsed['pages'][0]['text'].encode() == raw
    assert parsed['mime'] == 'application/json'


def test_html_scripts_are_not_text_or_instructions():
    parsed = extract(b'<html><script>steal tokens</script><p>document quotation</p></html>')
    assert 'steal tokens' not in parsed['pages'][0]['text']
    assert 'document quotation' in parsed['pages'][0]['text']


@pytest.mark.parametrize('filename', ['../outside.txt', '/outside', 'C:/outside', 'a/../../outside', '..\\outside'])
def test_archive_path_rejected(filename):
    raw = io.BytesIO()
    with ZipFile(raw, 'w') as archive:
        archive.writestr(filename, 'TEST FIXTURE')
    with pytest.raises(ValueError):
        archive_members(raw.getvalue())


def test_archive_pages_and_depth():
    raw = io.BytesIO()
    with ZipFile(raw, 'w') as archive:
        archive.writestr('one.json', '{"test_fixture":true}')
        archive.writestr('two.csv', 'key,value\na,1')
    assert len(extract(raw.getvalue())['pages']) == 2
    with pytest.raises(ValueError):
        extract(raw.getvalue(), depth=3)


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv('IGES_TEST_ADMIN_URL'), reason='disposable PostgreSQL required')
def test_document_claim_review_publication_correction(monkeypatch):
    identity = {'sub': 'TEST_ANALYST', 'project_id': '', 'roles': ['analyst', 'editor']}
    app.dependency_overrides[verified_identity] = lambda: identity
    monkeypatch.setenv('IGES_ENABLE_PUBLICATION', 'true')
    try:
        with TestClient(app) as client:
            def post(path, payload, rev=None, key=None, expected=201, raw=None):
                headers = {'Idempotency-Key': key or uuid4().hex}
                if rev is not None:
                    headers['If-Match'] = f'"{rev}"'
                response = client.post(path, json=payload, headers=headers) if raw is None else client.post(path, content=raw, headers=headers)
                assert response.status_code == expected, response.text
                return response.json()
            case = dict(title='TEST FIXTURE: documentary workflow', scope='TEST FIXTURE: no real-world finding',
                        period_from='2024-01-01', period_to='2024-12-31', jurisdictions=['PT'])
            key = uuid4().hex
            created = post('/v1/cases', case, key=key)
            assert post('/v1/cases', case, key=key) == created
            post('/v1/cases', case | {'title': 'different test fixture'}, key=key, expected=409)
            cid, rev = created['id'], created['case_revision']
            base = f'/v1/cases/{cid}'
            for sub, role in [('TEST_REVIEWER', 'reviewer'), ('TEST_COUNSEL', 'counsel')]:
                post(base + '/members', {'subject': sub, 'role': role}, rev)
            claim = post(base + '/claims', dict(exact_text='TEST FIXTURE quoted source contains population.',
                         period_from='2024-01-01', period_to='2024-12-31', jurisdictions=['PT'],
                         scope_note='TEST FIXTURE: document wording only', claim_type='documentary'), rev)
            rev = claim['case_revision']
            post(base + '/entities', {}, rev, expected=422)
            post(base + '/hypotheses', dict(claim_id=claim['id'], statement='TEST FIXTURE: expected document wording',
                 expected_observations='TEST FIXTURE: source contains quotation', falsifiers='TEST FIXTURE: quotation absent'), rev)
            rev += 1
            source = post(base + '/sources', dict(title='TEST FIXTURE source', publisher='TEST FIXTURE publisher',
                url='https://example.invalid/test-fixture', language='en', primacy='primary',
                independence_group='test-fixture-publisher', provenance_basis='TEST FIXTURE: not an actual source'), rev)
            rev = source['case_revision']
            raw = b'{"TEST_FIXTURE":"population source quotation"}'
            uploaded = post(base + '/documents?source_id=' + source['id'], None, rev, raw=raw)
            rev = uploaded['case_revision']
            quote = dict(claim_id=claim['id'], document_id=uploaded['id'], page=1,
                         quote='population', direction='supports', limitations=['TEST FIXTURE ONLY'])
            post(base + '/evidence-items', quote, rev, expected=409)
            # This fixture isolates business rules; actual scanner/OCR runs in the dedicated intake CI job.
            with tenant_session() as session:
                insert(session, 'document_pages', cid, identity, None, document_id=uploaded['id'], page=1,
                       text_content=raw.decode(), confidence=None, method='EXPLICIT_TEST_FIXTURE',
                       content_sha256=hashlib.sha256(raw).hexdigest())
                insert(session, 'document_processing', cid, identity, None, document_id=uploaded['id'], status='READY',
                       receipt=json.dumps({'TEST_FIXTURE': True}))
            post(base + '/evidence-items', quote | {'quote': 'absent quotation'}, rev, expected=409)
            evidence = post(base + '/evidence-items', quote, rev)
            rev = evidence['case_revision']
            assert client.get(base + '/search?q=population').json()['records']
            assignment = dict(claim_id=claim['id'], reviewer_sub='TEST_REVIEWER')
            post(base + '/review-assignments', assignment, rev)
            assessment = dict(claim_id=claim['id'], status='SUPPORTED', conflict_declaration='NO_CONFLICT',
                independence_rationale='TEST FIXTURE: separate reviewer', rationale='TEST FIXTURE: exact wording was checked',
                quotations_checked=True, provenance_checked=True, contradicting_material_considered='TEST FIXTURE: none in this bounded fixture',
                limitations='TEST FIXTURE: not a real-world verified finding')
            identity.update(sub='TEST_REVIEWER', roles=['reviewer'])
            post(base + '/assessments', assessment, rev)
            identity.update(sub='TEST_COUNSEL', roles=['counsel'])
            legal = dict(decision='APPROVE', rationale='TEST FIXTURE: this is only an isolated test',
                legal_basis='TEST FIXTURE: no actual legal approval', privacy_assessment='TEST FIXTURE: no personal data',
                copyright_basis='TEST FIXTURE: self-authored test material', public_content_approved=True,
                personal_data_minimised=True, retention_policy='TEST FIXTURE: disposable test database')
            post(base + '/legal-privacy', legal, rev)
            identity.update(sub='TEST_ANALYST', roles=['analyst', 'editor'])
            post(base + '/reply-window', dict(disposition='NO_AFFECTED_PARTY', rationale='TEST FIXTURE: no actual affected party'), rev)
            publication = dict(methodology_version='test-fixture/1', methodology='TEST FIXTURE: isolated business-rule validation, not a real-world assessment.',
                               reason='TEST FIXTURE: verify immutable publication')
            pub = post(base + '/publications', publication, rev)
            manifest_response = client.get('/v1/public/publications/' + pub['id'] + '/manifest')
            original_bytes = manifest_response.content
            assert hashlib.sha256(original_bytes).hexdigest() == pub['manifest_hash']
            assert b'TEST_ANALYST' not in original_bytes
            corrected = post(base + '/publications', publication | {'kind': 'CORRECTED', 'supersedes_id': pub['id'],
                'reason': 'TEST FIXTURE: explanatory correction'}, rev)
            assert corrected['version'] == 2
            assert client.get('/v1/public/publications/' + pub['id'] + '/manifest').content == original_bytes
            # Any content addition invalidates all prior revision approvals.
            post(base + '/entities', dict(entity_type='State', canonical_name='TEST FIXTURE state', aliases=[],
                jurisdiction='PT', external_ids={}, identity_confidence='unverified',
                identity_basis='TEST FIXTURE: unverified test identity'), rev)
            post(base + '/publications', publication | {'kind': 'CORRECTED', 'supersedes_id': corrected['id']}, rev + 1, expected=409)
            identity.update(sub='OUTSIDER', roles=['editor'])
            assert client.get(base).status_code == 404
            identity.update(sub='TEST_ANALYST', roles=['administrator'])
            post(base + '/entities', dict(entity_type='State', canonical_name='TEST FIXTURE', jurisdiction='PT',
                identity_confidence='unverified', identity_basis='TEST FIXTURE: no authority'), rev + 1, expected=403)
            with tenant_session() as session:
                assert session.execute(text('SELECT count(*) FROM publications WHERE case_id=:cid'), {'cid': cid}).scalar_one() == 2
    finally:
        app.dependency_overrides.clear()
