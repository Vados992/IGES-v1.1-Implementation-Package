"""Transactional, append-only workspace; all publication decisions belong to humans."""
from __future__ import annotations

import hashlib
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response as HTTPResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.auth import verified_identity, https_endpoint, require_role
from app.database import tenant_session
from app.persistence import append_audit
from app.config import settings
from app import workflow_models as m
from app.record_integrity import seal

router = APIRouter(tags=['Evidence workspace'])
TABLES = {'claims', 'hypotheses', 'sources', 'documents', 'evidence_items', 'entities',
          'relationships', 'entity_resolutions', 'case_revisions', 'case_member_revocations', 'review_assignments', 'assessments', 'publication_gates', 'responses'}


def canonical(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fail(code, status=409):
    raise HTTPException(status_code=status, detail=code)


def rows(session, sql, **params):
    return [dict(r) for r in session.execute(text(sql), params).mappings().all()]


def one(session, sql, **params):
    found = rows(session, sql, **params)
    if not found:
        fail('OBJECT_NOT_FOUND', 404)
    return found[0]


def revision(session, cid):
    return session.execute(text('SELECT coalesce(max(revision),0) FROM case_events WHERE case_id=:id'),
                           {'id': str(cid)}).scalar_one()


def access(session, cid, user, roles=None):
    case = one(session, 'SELECT * FROM cases WHERE id=:id', id=str(cid))
    memberships = rows(session, 'SELECT role FROM case_members m WHERE case_id=:id AND subject=:sub '
                       'AND NOT EXISTS(SELECT 1 FROM case_member_revocations r WHERE r.member_id=m.id)',
                       id=str(cid), sub=user['sub'])
    case_roles = {r['role'] for r in memberships}
    if not case_roles:
        fail('CASE_NOT_FOUND', 404)
    if not case_roles & set(user.get('roles', [])):
        fail('CURRENT_IDENTITY_ROLE_REQUIRED', 403)
    if roles and not (case_roles & set(roles) & set(user.get('roles', []))):
        fail('CASE_ROLE_DENIED', 403)
    amendments = rows(session, 'SELECT body FROM case_revisions WHERE case_id=:id ORDER BY created_at DESC,id DESC LIMIT 1', id=str(cid))
    if amendments:
        case['body'] = amendments[0]['body']
    return case


def insert(session, table, cid, user, body, **fields):
    if table not in TABLES | {'cases', 'case_members', 'document_pages', 'document_processing',
                             'publications', 'integrity_incidents'}:
        raise ValueError('Table not allowlisted')
    values = {'id': str(uuid4()), 'project_id': str(settings.project_id), 'case_id': str(cid),
              'created_by': user['sub'], **fields}
    if table == 'cases':
        values.pop('case_id')
    if body is not None:
        values['body'] = canonical(body)
    cols = list(values)
    parameters = ','.join('CAST(:body AS jsonb)' if c == 'body' else
                          f'CAST(:{c} AS jsonb)' if c in {'receipt', 'locator'} else ':' + c for c in cols)
    stored = session.execute(text(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({parameters}) RETURNING *"), values).mappings().one()  # noqa: S608  # nosec B608
    seal(session, table, dict(stored))
    return values['id']


def content_event(session, cid, user, action, payload):
    rev = revision(session, cid) + 1
    canon = canonical(payload)
    sha = hashlib.sha256(canon.encode()).hexdigest()
    session.execute(text('INSERT INTO case_events(project_id,case_id,revision,action,payload,'
                         'canonical_payload,payload_sha256,created_by) VALUES '
                         '(:pid,:cid,:rev,:action,CAST(:payload AS jsonb),:canon,:sha,:actor)'),
                    {'pid': str(settings.project_id), 'cid': str(cid), 'rev': rev, 'action': action,
                     'payload': canon, 'canon': canon, 'sha': sha, 'actor': user['sub']})
    append_audit(session, user['sub'], action, f'{cid}:{rev}:{sha}')
    return rev


class Writer:
    def __init__(self, request: Request, user: dict = Depends(verified_identity),
                 key: str = Header(alias='Idempotency-Key', min_length=8, max_length=128),
                 match: str | None = Header(default=None, alias='If-Match')):
        self.request, self.user, self.key, self.match = request, user, key, match

    def run(self, cid, roles, payload, action, operation, *, content=True, creating=False):
        path = self.request.method + ' ' + self.request.url.path
        hashed = digest({'payload': payload, 'query': str(self.request.url.query)})
        actor = self.user['sub']
        with tenant_session() as session:
            # Same lock order for receipt, case and audit; replays and concurrent publication are atomic.
            lock_key = f'write:{actor}:{path}:{self.key}'
            session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'), {'key': lock_key})
            if not creating:
                session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                                {'key': 'case:' + str(cid)})
                access(session, cid, self.user, roles)
            elif not set(roles) & set(self.user.get('roles', [])):
                fail('ROLE_DENIED', 403)
            prior = rows(session, 'SELECT * FROM write_receipts WHERE actor=:actor AND request_path=:path AND key=:key',
                         actor=actor, path=path, key=self.key)
            if prior:
                if prior[0]['request_hash'] != hashed:
                    fail('IDEMPOTENCY_CONFLICT')
                return prior[0]['response']
            rev = 0 if creating else revision(session, cid)
            if not creating and self.match != f'"{rev}"':
                fail('IF_MATCH_REQUIRED_OR_STALE', 412)
            result = operation(session, rev)
            actual_cid = result['id'] if creating else str(cid)
            audited = {'request': payload, 'result': result}
            if content:
                rev = content_event(session, actual_cid, self.user, action, audited)
            else:
                append_audit(session, actor, action, str(actual_cid) + ':' + digest(audited))
            result = jsonable_encoder({**result, 'case_revision': rev})
            session.execute(text('INSERT INTO write_receipts(project_id,actor,request_path,key,request_hash,response) '
                                 'VALUES(:pid,:actor,:path,:key,:hash,CAST(:response AS jsonb))'),
                            {'pid': str(settings.project_id), 'actor': actor, 'path': path, 'key': self.key,
                             'hash': hashed, 'response': canonical(result)})
            return result


@router.post('/v1/cases', status_code=201)
def create_case(body: m.Case, writer: Writer = Depends()):
    def create(session, rev):
        cid = insert(session, 'cases', uuid4(), writer.user, body.model_dump(mode='json'))
        for role in {'analyst', 'editor'} & set(writer.user.get('roles', [])):
            insert(session, 'case_members', cid, writer.user, None, subject=writer.user['sub'], role=role)
        return {'id': cid}
    return writer.run(None, ['analyst', 'editor'], body.model_dump(mode='json'), 'CASE_CREATED', create, creating=True)


@router.get('/v1/cases')
def list_cases(user: dict = Depends(verified_identity), limit: int = Query(50, ge=1, le=100), cursor: UUID | None = None):
    with tenant_session(read_only=True) as session:
        return {'records': rows(session, 'SELECT id,coalesce((SELECT body FROM case_revisions cr WHERE cr.case_id=c.id ORDER BY created_at DESC,id DESC LIMIT 1),c.body) AS body,created_at FROM cases c WHERE EXISTS '
                                '(SELECT 1 FROM case_members m WHERE m.case_id=c.id AND m.subject=:sub AND m.role=ANY(:roles) '
                                'AND NOT EXISTS(SELECT 1 FROM case_member_revocations r WHERE r.member_id=m.id)) '
                                'AND (CAST(:cursor AS uuid) IS NULL OR c.id>CAST(:cursor AS uuid)) ORDER BY c.id LIMIT :limit',
                                sub=user['sub'], roles=user.get('roles', []), cursor=str(cursor) if cursor else None, limit=limit)}


@router.get('/v1/cases/{cid}')
def get_case(cid: UUID, user: dict = Depends(verified_identity)):
    with tenant_session(read_only=True, repeatable_read=True) as session:
        case = access(session, cid, user)
        records = {}
        for table in sorted(TABLES):
            cols = ("id,source_id,sha256,mime,size_bytes,doc_version,retrieved_at,"
                    "(SELECT status FROM document_processing p WHERE p.document_id=documents.id ORDER BY created_at DESC,id DESC LIMIT 1) AS processing_status,"
                    "(SELECT receipt->>'mime' FROM document_processing p WHERE p.document_id=documents.id ORDER BY created_at DESC,id DESC LIMIT 1) AS detected_mime") if table == 'documents' else '*'
            records[table] = rows(session, f'SELECT {cols} FROM {table} WHERE case_id=:id ORDER BY id LIMIT 501', id=str(cid))  # noqa: S608 -- fixed TABLES allowlist  # nosec B608
        records['publications'] = rows(session, 'SELECT id,version,revision,kind,supersedes_id,manifest_hash FROM publications WHERE case_id=:id ORDER BY version', id=str(cid))
        return jsonable_encoder({'id': cid, 'body': case['body'], 'case_revision': revision(session, cid),
                                 'records': records, 'record_limit': 500})


@router.post('/v1/cases/{cid}/members', status_code=201)
def add_member(cid: UUID, body: m.Member, writer: Writer = Depends()):
    def add(session, rev):
        case = one(session, 'SELECT created_by FROM cases WHERE id=:id', id=str(cid))
        if case['created_by'] != writer.user['sub']:
            fail('ONLY_CASE_OWNER_CAN_GRANT_MEMBERSHIP', 403)
        if rows(session, 'SELECT id FROM case_members m WHERE case_id=:cid AND subject=:sub AND role=:role '
                'AND NOT EXISTS(SELECT 1 FROM case_member_revocations r WHERE r.member_id=m.id)',
                cid=str(cid), sub=body.subject, role=body.role):
            fail('MEMBERSHIP_ALREADY_ACTIVE')
        return {'id': insert(session, 'case_members', cid, writer.user, None, **body.model_dump())}
    return writer.run(cid, ['analyst', 'editor'], body.model_dump(), 'CASE_MEMBER_GRANTED', add, content=False)


@router.post('/v1/cases/{cid}/member-revocations', status_code=201)
def revoke_member(cid: UUID, body: m.MemberRevocation, writer: Writer = Depends()):
    def revoke(session, rev):
        case = one(session, 'SELECT created_by FROM cases WHERE id=:id', id=str(cid))
        if case['created_by'] != writer.user['sub']:
            fail('ONLY_CASE_OWNER_CAN_REVOKE_MEMBERSHIP', 403)
        one(session, 'SELECT id FROM case_members WHERE id=:id AND case_id=:cid', id=str(body.member_id), cid=str(cid))
        return {'id': insert(session, 'case_member_revocations', cid, writer.user, body.model_dump(mode='json'), member_id=str(body.member_id))}
    return writer.run(cid, ['analyst', 'editor'], body.model_dump(mode='json'), 'CASE_MEMBER_REVOKED', revoke, content=False)


def create_record(cid, body, writer, table, fields=None):
    payload = body.model_dump(mode='json')
    def add(session, rev):
        extra = {name: payload[name] for name in fields or []}
        if table == 'claims':
            if body.supersedes_id:
                one(session, 'SELECT id FROM claims WHERE id=:id AND case_id=:cid', id=str(body.supersedes_id), cid=str(cid))
                if not rows(session, "SELECT id FROM assessments WHERE claim_id=:id AND status='WITHDRAWN_CORRECTED'", id=str(body.supersedes_id)):
                    fail('WITHDRAW_PRIOR_CLAIM_BEFORE_SUPERSEDING')
            extra.update(statement=body.exact_text, submitted_by=writer.user['sub'])
        if table == 'sources' and not https_endpoint(body.url):
            fail('SOURCE_HTTPS_REQUIRED', 422)
        if table == 'evidence_items':
            verify_document(session, cid, body.document_id)
        return {'id': insert(session, table, cid, writer.user, payload, **extra)}
    return writer.run(cid, ['analyst', 'editor'], payload, table.upper() + '_CREATED', add)


@router.post('/v1/cases/{cid}/claims', status_code=201)
def create_claim(cid: UUID, body: m.Claim, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'claims')


@router.post('/v1/cases/{cid}/case-revisions', status_code=201)
def amend_case(cid: UUID, body: m.CaseRevision, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'case_revisions')


@router.post('/v1/cases/{cid}/hypotheses', status_code=201)
def create_hypothesis(cid: UUID, body: m.Hypothesis, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'hypotheses', ['claim_id'])


@router.post('/v1/cases/{cid}/sources', status_code=201)
def create_source(cid: UUID, body: m.Source, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'sources')


@router.post('/v1/cases/{cid}/evidence-items', status_code=201)
def create_evidence(cid: UUID, body: m.EvidenceItem, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'evidence_items', ['claim_id', 'document_id', 'page', 'quote', 'direction'])


@router.post('/v1/cases/{cid}/entities', status_code=201)
def create_entity(cid: UUID, body: m.Entity, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'entities')


@router.post('/v1/cases/{cid}/relationships', status_code=201)
def create_relationship(cid: UUID, body: m.Relationship, writer: Writer = Depends()):
    return create_record(cid, body, writer, 'relationships', ['subject_id', 'object_id', 'evidence_id'])


@router.post('/v1/cases/{cid}/entity-resolutions', status_code=201)
def resolve_entity(cid: UUID, body: m.EntityResolution, writer: Writer = Depends()):
    def add(session, rev):
        if body.subject_id == body.object_id:
            fail('ENTITY_CANNOT_MERGE_WITH_ITSELF', 422)
        for eid in [body.subject_id, body.object_id]:
            one(session, 'SELECT id FROM entities WHERE id=:id AND case_id=:cid', id=str(eid), cid=str(cid))
        prior = rows(session, 'SELECT DISTINCT ON(subject_id) id,subject_id,object_id,body FROM entity_resolutions '
                     'WHERE case_id=:cid ORDER BY subject_id,created_at DESC,id DESC', cid=str(cid))
        own = next((r for r in prior if str(r['subject_id']) == str(body.subject_id)), None)
        if body.action == 'UNDO_MERGE':
            if not own or own['body']['action'] != 'MERGE_ALIAS' or str(own['id']) != str(body.reverses_id) or own['object_id'] != body.object_id:
                fail('UNDO_MUST_REFERENCE_ACTIVE_MERGE')
        else:
            if body.reverses_id or (own and own['body']['action'] == 'MERGE_ALIAS'):
                fail('UNDO_ACTIVE_MERGE_BEFORE_REASSIGNING')
            edges = {str(r['subject_id']): str(r['object_id']) for r in prior if r['body']['action'] == 'MERGE_ALIAS'}
            cursor, visited = str(body.object_id), {str(body.subject_id)}
            while cursor:
                if cursor in visited:
                    fail('ENTITY_ALIAS_CYCLE_FORBIDDEN')
                visited.add(cursor)
                cursor = edges.get(cursor)
        return {'id': insert(session, 'entity_resolutions', cid, writer.user, body.model_dump(mode='json'),
                             subject_id=str(body.subject_id), object_id=str(body.object_id), evidence_id=str(body.evidence_id))}
    return writer.run(cid, ['analyst', 'editor'], body.model_dump(mode='json'), 'ENTITY_RESOLUTION_RECORDED', add)


@router.post('/v1/cases/{cid}/claims/{claim_id}/withdrawal', status_code=201)
def withdraw_claim(cid: UUID, claim_id: UUID, body: m.Withdrawal, writer: Writer = Depends()):
    def add(session, rev):
        claim = one(session, 'SELECT submitted_by FROM claims WHERE id=:id AND case_id=:cid', id=str(claim_id), cid=str(cid))
        if claim['submitted_by'] != writer.user['sub']:
            fail('ONLY_AUTHOR_CAN_USE_AUTHOR_WITHDRAWAL', 403)
        if rows(session, "SELECT id FROM assessments WHERE claim_id=:id AND status='WITHDRAWN_CORRECTED'", id=str(claim_id)):
            fail('CLAIM_ALREADY_WITHDRAWN')
        payload = {**body.model_dump(), 'author_withdrawal': True,
                   'limitations': 'Withdrawn by the author; no substantive finding is implied.'}
        return {'id': insert(session, 'assessments', cid, writer.user, payload, claim_id=str(claim_id),
                             revision=rev, status='WITHDRAWN_CORRECTED')}
    return writer.run(cid, ['analyst', 'editor'], body.model_dump(), 'AUTHOR_WITHDREW_CLAIM', add)


@router.post('/v1/cases/{cid}/documents', status_code=201, openapi_extra={
    'requestBody': {'required': True, 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
async def upload_document(cid: UUID, source_id: UUID, request: Request, writer: Writer = Depends()):
    raw = await request.body()
    if not raw or len(raw) > 8388608:
        fail('DOCUMENT_SIZE_LIMIT', 413)
    sha = hashlib.sha256(raw).hexdigest()
    def store(session, rev):
        one(session, 'SELECT id FROM sources WHERE id=:id AND case_id=:cid', id=str(source_id), cid=str(cid))
        previous = rows(session, 'SELECT id FROM documents WHERE source_id=:id AND sha256=:sha', id=str(source_id), sha=sha)
        if previous:
            return {'id': str(previous[0]['id']), 'sha256': sha, 'duplicate': True}
        version = session.execute(text('SELECT coalesce(max(doc_version),0)+1 FROM documents WHERE source_id=:id'),
                                  {'id': str(source_id)}).scalar_one()
        did = insert(session, 'documents', cid, writer.user, None, source_id=str(source_id), sha256=sha,
                     raw_bytes=raw, mime='application/octet-stream', size_bytes=len(raw), doc_version=version)
        return {'id': did, 'sha256': sha, 'status': 'PENDING', 'doc_version': version}
    return await run_in_threadpool(writer.run, cid, ['analyst', 'editor'], {'sha256': sha}, 'DOCUMENT_RECEIVED', store)


def verify_document(session, cid, did):
    doc = one(session, 'SELECT * FROM documents WHERE id=:id AND case_id=:cid', id=str(did), cid=str(cid))
    if hashlib.sha256(bytes(doc['raw_bytes'])).hexdigest() != doc['sha256']:
        fail('DOCUMENT_HASH_MISMATCH')
    processing = rows(session, 'SELECT * FROM document_processing WHERE document_id=:id ORDER BY created_at DESC,id DESC LIMIT 1', id=str(did))
    if not processing or processing[0]['status'] != 'READY':
        fail('DOCUMENT_NOT_READY')
    return doc


@router.get('/v1/cases/{cid}/documents/{did}/original')
def original(cid: UUID, did: UUID, user: dict = Depends(verified_identity)):
    with tenant_session() as session:
        access(session, cid, user, ['analyst', 'editor', 'reviewer', 'counsel'])
        doc = verify_document(session, cid, did)
        append_audit(session, user['sub'], 'ORIGINAL_ACCESSED', str(did))
        return HTTPResponse(bytes(doc['raw_bytes']), media_type='application/octet-stream',
                            headers={'Content-Disposition': f'attachment; filename="{did}.original"',
                                     'X-Content-SHA256': doc['sha256'], 'ETag': '"' + doc['sha256'] + '"'})


@router.get('/v1/cases/{cid}/documents/{did}/pages')
def pages(cid: UUID, did: UUID, user: dict = Depends(verified_identity)):
    with tenant_session(read_only=True) as session:
        access(session, cid, user)
        one(session, 'SELECT id FROM documents WHERE id=:id AND case_id=:cid', id=str(did), cid=str(cid))
        return {'pages': rows(session, 'SELECT page,text_content,confidence,method,locator,content_sha256 FROM document_pages '
                              'WHERE document_id=:id ORDER BY page', id=str(did)),
                'processing': rows(session, 'SELECT status,receipt,created_at FROM document_processing WHERE document_id=:id '
                                   'ORDER BY created_at DESC LIMIT 1', id=str(did))}


@router.post('/v1/cases/{cid}/documents/{did}/verify')
def reverify(cid: UUID, did: UUID, writer: Writer = Depends()):
    def check(session, rev):
        doc = one(session, 'SELECT sha256,raw_bytes FROM documents WHERE id=:id AND case_id=:cid', id=str(did), cid=str(cid))
        observed = hashlib.sha256(bytes(doc['raw_bytes'])).hexdigest()
        if observed != doc['sha256']:
            # Persist an incident even though verification failed; no exception rollback.
            values = {'id': str(uuid4()), 'pid': str(settings.project_id), 'did': str(did), 'sha': observed,
                      'sub': writer.user['sub']}
            session.execute(text('INSERT INTO integrity_incidents(id,project_id,document_id,observed_hash,created_by) '
                                 'VALUES(:id,:pid,:did,:sha,:sub)'), values)
        return {'id': str(did), 'integrity_checked': observed == doc['sha256'], 'observed_sha256': observed,
                'meaning': 'Hash integrity does not establish truth or authenticity'}
    return writer.run(cid, ['analyst', 'editor', 'reviewer'], {'id': str(did)}, 'DOCUMENT_REVERIFIED', check, content=False)


@router.post('/v1/cases/{cid}/documents/{did}/retry')
def retry_document(cid: UUID, did: UUID, writer: Writer = Depends()):
    def retry(session, rev):
        one(session, 'SELECT id FROM documents WHERE id=:id AND case_id=:cid', id=str(did), cid=str(cid))
        latest = one(session, 'SELECT status FROM document_processing WHERE document_id=:id '
                     'ORDER BY created_at DESC,id DESC LIMIT 1', id=str(did))
        if latest['status'] not in {'FAILED', 'QUARANTINED'}:
            fail('ONLY_FAILED_INTAKE_CAN_BE_RETRIED')
        return {'id': insert(session, 'document_processing', cid, writer.user, None, document_id=str(did),
                             status='RETRY_REQUESTED', receipt=canonical({'retry_requested_by': writer.user['sub']}))}
    return writer.run(cid, ['analyst', 'editor'], {'id': str(did)}, 'DOCUMENT_RETRY_REQUESTED', retry, content=False)


@router.get('/v1/cases/{cid}/search')
def search(cid: UUID, q: str = Query(min_length=2, max_length=200), user: dict = Depends(verified_identity),
           limit: int = Query(30, ge=1, le=100), cursor: UUID | None = None):
    with tenant_session(read_only=True) as session:
        access(session, cid, user)
        return {'records': rows(session, """SELECT * FROM (
          SELECT id,'document' AS kind,document_id AS object_id,page,
            ts_headline('simple',text_content,plainto_tsquery('simple',:q),'StartSel=,StopSel=') AS fragment
            FROM document_pages WHERE case_id=:cid AND search_vector @@ plainto_tsquery('simple',:q)
          UNION ALL SELECT id,'claim',id,NULL,statement FROM claims WHERE case_id=:cid
            AND to_tsvector('simple',statement) @@ plainto_tsquery('simple',:q)
          UNION ALL SELECT id,'entity',id,NULL,body->>'canonical_name' FROM entities WHERE case_id=:cid
            AND to_tsvector('simple',body::text) @@ plainto_tsquery('simple',:q)
          ) found WHERE (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT :limit""",
                                cid=str(cid), q=q, limit=limit, cursor=str(cursor) if cursor else None)}


@router.post('/v1/cases/{cid}/review-assignments', status_code=201)
def assign(cid: UUID, body: m.Assignment, writer: Writer = Depends()):
    def add(session, rev):
        one(session, "SELECT id FROM case_members WHERE case_id=:cid AND subject=:sub AND role='reviewer'",
            cid=str(cid), sub=body.reviewer_sub)
        return {'id': insert(session, 'review_assignments', cid, writer.user, None, **body.model_dump(mode='json'))}
    return writer.run(cid, ['editor', 'analyst'], body.model_dump(mode='json'), 'REVIEW_ASSIGNED', add, content=False)


def independent(session, cid, user, claim_id=None):
    params = {'cid': str(cid), 'sub': user['sub']}
    if claim_id:
        params['claim'] = str(claim_id)
        author = rows(session, 'SELECT 1 FROM claims WHERE id=:claim AND case_id=:cid AND submitted_by=:sub '
                      'UNION ALL SELECT 1 FROM evidence_items WHERE claim_id=:claim AND case_id=:cid AND created_by=:sub '
                      'UNION ALL SELECT 1 FROM hypotheses WHERE claim_id=:claim AND case_id=:cid AND created_by=:sub '
                      'UNION ALL SELECT 1 FROM documents d JOIN evidence_items e ON e.document_id=d.id '
                      'WHERE e.claim_id=:claim AND e.case_id=:cid AND d.created_by=:sub', **params)
    else:
        author = rows(session, 'SELECT 1 FROM claims WHERE case_id=:cid AND submitted_by=:sub '
                      'UNION ALL SELECT 1 FROM evidence_items WHERE case_id=:cid AND created_by=:sub '
                      'UNION ALL SELECT 1 FROM documents WHERE case_id=:cid AND created_by=:sub', **params)
    if author:
        fail('SELF_REVIEW_OR_CONFLICT_FORBIDDEN', 403)


@router.post('/v1/cases/{cid}/assessments', status_code=201)
def assess(cid: UUID, body: m.Assessment, writer: Writer = Depends()):
    def add(session, rev):
        independent(session, cid, writer.user, body.claim_id)
        one(session, 'SELECT id FROM review_assignments WHERE case_id=:cid AND claim_id=:claim AND reviewer_sub=:sub',
            cid=str(cid), claim=str(body.claim_id), sub=writer.user['sub'])
        one(session, 'SELECT id FROM hypotheses WHERE case_id=:cid AND claim_id=:claim', cid=str(cid), claim=str(body.claim_id))
        evidence = rows(session, 'SELECT e.*,p.confidence FROM evidence_items e JOIN document_pages p '
                        'ON p.document_id=e.document_id AND p.page=e.page WHERE e.case_id=:cid AND e.claim_id=:claim',
                        cid=str(cid), claim=str(body.claim_id))
        if not evidence:
            fail('EVIDENCE_REQUIRED')
        for item in evidence:
            verify_document(session, cid, item['document_id'])
        if any(e['confidence'] is not None and e['confidence'] < .85 for e in evidence):
            if not body.low_confidence_pages_visually_checked:
                fail('MANUAL_OCR_COMPARISON_REQUIRED')
        retired = rows(session, "SELECT id FROM assessments WHERE claim_id=:id AND status='WITHDRAWN_CORRECTED'",
                       id=str(body.claim_id))
        if retired:
            fail('WITHDRAWAL_IS_IRREVERSIBLE_CREATE_SUPERSEDING_CLAIM')
        previous = rows(session, 'SELECT status,revision FROM assessments WHERE claim_id=:id AND created_by=:actor ORDER BY revision DESC,created_at DESC LIMIT 1', id=str(body.claim_id), actor=writer.user['sub'])
        if previous and previous[0]['status'] != body.status and body.status != 'WITHDRAWN_CORRECTED':
            fresh = rows(session, "SELECT id FROM case_events WHERE case_id=:cid AND revision>:rev AND action='EVIDENCE_ITEMS_CREATED' AND payload->'request'->>'claim_id'=:claim",
                         cid=str(cid), rev=previous[0]['revision'], claim=str(body.claim_id))
            if not fresh:
                fail('NEW_EVIDENCE_REQUIRED_FOR_CHANGED_ASSESSMENT')
        return {'id': insert(session, 'assessments', cid, writer.user, body.model_dump(mode='json'),
                             claim_id=str(body.claim_id), revision=rev, status=body.status)}
    return writer.run(cid, ['reviewer'], body.model_dump(mode='json'), 'CLAIM_ASSESSED', add, content=False)


def gate(cid, body, writer, name, roles):
    def add(session, rev):
        if name != 'reply':
            independent(session, cid, writer.user)
        if name == 'panel' and rows(session, 'SELECT id FROM assessments WHERE case_id=:cid AND created_by=:sub',
                                   cid=str(cid), sub=writer.user['sub']):
            fail('PANEL_MUST_BE_INDEPENDENT_OF_REVIEWERS', 403)
        if name == 'reply' and body.disposition == 'REQUEST_RECORDED':
            one(session, 'SELECT id FROM evidence_items WHERE id=:id AND case_id=:cid',
                id=str(body.request_evidence_id), cid=str(cid))
            if body.deadline < datetime.now(timezone.utc) + timedelta(days=14):
                fail('RESPONSE_WINDOW_MINIMUM_14_DAYS', 422)
        return {'id': insert(session, 'publication_gates', cid, writer.user, body.model_dump(mode='json'),
                             revision=rev, gate=name)}
    return writer.run(cid, roles, body.model_dump(mode='json'), name.upper() + '_GATE_RECORDED', add, content=False)


@router.post('/v1/cases/{cid}/legal-privacy', status_code=201)
def legal(cid: UUID, body: m.LegalGate, writer: Writer = Depends()):
    return gate(cid, body, writer, 'legal_privacy', ['counsel'])


@router.post('/v1/cases/{cid}/panel', status_code=201)
def panel(cid: UUID, body: m.PanelGate, writer: Writer = Depends()):
    return gate(cid, body, writer, 'panel', ['panel'])


@router.post('/v1/cases/{cid}/reply-window', status_code=201)
def reply(cid: UUID, body: m.ReplyGate, writer: Writer = Depends()):
    return gate(cid, body, writer, 'reply', ['editor'])


@router.post('/v1/cases/{cid}/responses', status_code=201)
def response(cid: UUID, body: m.Response, writer: Writer = Depends()):
    def add(session, rev):
        for eid in body.evidence_refs:
            one(session, 'SELECT id FROM evidence_items WHERE id=:id AND case_id=:cid', id=str(eid), cid=str(cid))
        return {'id': insert(session, 'responses', cid, writer.user, body.model_dump(mode='json'))}
    return writer.run(cid, ['respondent'], body.model_dump(mode='json'), 'PARTY_RESPONSE_RECEIVED', add)


def claims_csv(claims):
    target = io.StringIO(newline='')
    writer = csv.writer(target, lineterminator='\n')
    writer.writerow(['id', 'exact_text', 'period_from', 'period_to', 'status'])
    for claim in sorted(claims, key=lambda c: c['id']):
        cells = [str(claim[key]) for key in ['id', 'exact_text', 'period_from', 'period_to', 'status']]
        writer.writerow(["'" + cell if cell.startswith(('=', '+', '-', '@', '\t', '\r')) else cell for cell in cells])
    return target.getvalue().encode('utf-8')


def latest_gate(session, cid, rev, name):
    found = rows(session, 'SELECT * FROM publication_gates WHERE case_id=:cid AND revision=:rev AND gate=:gate '
                 'ORDER BY created_at DESC,id DESC LIMIT 1', cid=str(cid), rev=rev, gate=name)
    if not found:
        fail(name.upper() + '_GATE_REQUIRED')
    return found[0]


@router.post('/v1/cases/{cid}/publications', status_code=201)
def publish(cid: UUID, body: m.Publication, writer: Writer = Depends()):
    def build(session, rev):
        if os.getenv('IGES_ENABLE_PUBLICATION') != 'true':
            fail('PUBLICATION_DISABLED_OPERATOR_GATE', 403)
        legal = latest_gate(session, cid, rev, 'legal_privacy')['body']
        if legal['decision'] != 'APPROVE' or not legal['public_content_approved'] or not legal['personal_data_minimised']:
            fail('LEGAL_PRIVACY_VETO')
        reply = latest_gate(session, cid, rev, 'reply')
        responses = rows(session, 'SELECT id,body FROM responses WHERE case_id=:cid ORDER BY id', cid=str(cid))
        reply_body = reply['body']
        if reply_body['disposition'] == 'REQUEST_RECORDED' and not responses:
            if datetime.fromisoformat(reply_body['deadline']) > datetime.now(timezone.utc):
                fail('RESPONSE_WINDOW_OPEN')
        claim_rows = rows(session, 'SELECT id,body FROM claims WHERE case_id=:cid ORDER BY id', cid=str(cid))
        if not claim_rows:
            fail('CLAIMS_REQUIRED')
        conclusions = []
        for claim in claim_rows:
            decisions = rows(session, 'SELECT id,status,body FROM assessments WHERE case_id=:cid AND claim_id=:claim '
                             'AND revision=:rev ORDER BY created_at,id', cid=str(cid), claim=str(claim['id']), rev=rev)
            retired = rows(session, "SELECT id,status,body FROM assessments WHERE claim_id=:claim AND status='WITHDRAWN_CORRECTED' ORDER BY revision DESC LIMIT 1", claim=str(claim['id']))
            if retired:
                decisions = retired
            elif not decisions:
                fail('CURRENT_INDEPENDENT_REVIEW_REQUIRED')
            final_status = decisions[0]['status']
            if len({d['status'] for d in decisions}) > 1:
                panel_body = latest_gate(session, cid, rev, 'panel')['body']
                if panel_body['decision'] != 'APPROVE':
                    fail('PANEL_VETO')
                final_status = panel_body['claim_statuses'].get(str(claim['id']))
                if not final_status:
                    fail('PANEL_MUST_EXPLICITLY_RESOLVE_CLAIM')
            conclusions.append({'id': str(claim['id']), **claim['body'], 'status': final_status,
                                'reviews': [{'id': str(d['id']), 'assessment': d['body']} for d in decisions]})
        previous = rows(session, 'SELECT id,version FROM publications WHERE case_id=:cid ORDER BY version DESC LIMIT 1', cid=str(cid))
        if previous:
            if body.kind == 'PUBLISHED' or str(body.supersedes_id) != str(previous[0]['id']):
                fail('CORRECTION_MUST_SUPERSEDE_LATEST_VERSION')
        elif body.kind != 'PUBLISHED' or body.supersedes_id:
            fail('FIRST_VERSION_MUST_BE_PUBLISHED')
        docs = rows(session, 'SELECT id,source_id,sha256,size_bytes,doc_version FROM documents WHERE case_id=:cid ORDER BY id', cid=str(cid))
        for doc in docs:
            verify_document(session, cid, doc['id'])
            doc['extraction'] = rows(session, 'SELECT page,content_sha256,confidence,method,locator FROM document_pages WHERE document_id=:id ORDER BY page', id=doc['id'])
            doc['processing'] = one(session, "SELECT receipt FROM document_processing WHERE document_id=:id AND status='READY' ORDER BY created_at DESC LIMIT 1", id=doc['id'])['receipt']
        public_records = {}
        for table in ['hypotheses', 'sources', 'evidence_items', 'entities', 'relationships', 'entity_resolutions']:
            public_records[table] = rows(session, f'SELECT id,body FROM {table} WHERE case_id=:cid ORDER BY id', cid=str(cid))  # noqa: S608 -- fixed internal list  # nosec B608
        version = previous[0]['version'] + 1 if previous else 1
        manifest = {'schema': 'iges-publication/1', 'case_id': str(cid), 'version': version, 'revision': rev,
                    'case': access(session, cid, writer.user)['body'],
                    'kind': body.kind, 'reason': body.reason, 'supersedes_id': body.supersedes_id,
                    'methodology_version': body.methodology_version, 'methodology': body.methodology,
                    'claims': conclusions, 'documents': docs, 'records': public_records, 'responses': responses,
                    'reply_disposition': reply_body, 'legal_review': {'decision': legal['decision'],
                     'legal_basis': legal['legal_basis'], 'privacy_assessment': legal['privacy_assessment']},
                    'meaning': 'Human-reviewed scoped findings; hashes establish integrity, not truth or legal guilt'}
        manifest['exports'] = {'claims_csv_sha256': hashlib.sha256(claims_csv(conclusions)).hexdigest(),
                               'encoding': 'UTF-8', 'line_endings': 'LF', 'spreadsheet_formula_protection': True}
        manifest['case_revision_sha256'] = one(session, 'SELECT payload_sha256 FROM case_events WHERE case_id=:cid AND revision=:rev', cid=str(cid), rev=rev)['payload_sha256']
        canon = canonical(manifest)
        sha = hashlib.sha256(canon.encode()).hexdigest()
        pid = insert(session, 'publications', cid, writer.user, None, version=version, revision=rev,
                     kind=body.kind, supersedes_id=str(body.supersedes_id) if body.supersedes_id else None,
                     canonical_manifest=canon, manifest_hash=sha)
        # Commit the manifest hash itself into the independently checkable audit chain.
        append_audit(session, writer.user['sub'], 'PUBLICATION_MANIFEST', f'{pid}:{sha}')
        return {'id': pid, 'version': version, 'manifest_hash': sha, 'kind': body.kind}
    return writer.run(cid, ['editor'], body.model_dump(mode='json'), 'CASE_PUBLICATION_CREATED', build, content=False)


@router.get('/v1/public/cases/{cid}/publications')
def public_history(cid: UUID):
    with tenant_session(read_only=True) as session:
        history = rows(session, 'SELECT id,version,kind,supersedes_id,manifest_hash,created_at FROM publications '
                       'WHERE case_id=:cid ORDER BY version', cid=str(cid))
        for record in history:
            successor = next((r for r in history if r['supersedes_id'] == record['id']), None)
            record['superseded_by'] = successor['id'] if successor else None
            record['current'] = successor is None
        return {'records': history}


@router.get('/v1/public/publications/{pid}/manifest')
def public_manifest(pid: UUID):
    with tenant_session(read_only=True) as session:
        pub = one(session, 'SELECT canonical_manifest,manifest_hash FROM publications WHERE id=:id', id=str(pid))
        return HTTPResponse(pub['canonical_manifest'], media_type='application/json',
                            headers={'ETag': '"' + pub['manifest_hash'] + '"',
                                     'X-Manifest-SHA256': pub['manifest_hash']})


@router.get('/v1/cases/{cid}/audit')
def audit(cid: UUID, user: dict = Depends(verified_identity), after: int = Query(0, ge=0)):
    with tenant_session(read_only=True) as session:
        access(session, cid, user, ['editor', 'counsel'])
        return {'events': rows(session, 'SELECT revision,action,payload_sha256,created_at FROM case_events '
                               'WHERE case_id=:cid AND revision>:after ORDER BY revision LIMIT 100', cid=str(cid), after=after)}


@router.get('/v1/public/publications/{pid}/claims.csv')
def export_csv(pid: UUID):
    with tenant_session(read_only=True) as session:
        pub = one(session, 'SELECT canonical_manifest FROM publications WHERE id=:id', id=str(pid))
        manifest = json.loads(pub['canonical_manifest'])
        content = claims_csv(manifest['claims'])
        sha = hashlib.sha256(content).hexdigest()
        if sha != manifest['exports']['claims_csv_sha256']:
            fail('EXPORT_INTEGRITY_FAILED', 503)
        return HTTPResponse(content, media_type='text/csv; charset=utf-8', headers={
            'Content-Disposition': f'attachment; filename="{pid}-claims.csv"', 'X-Content-SHA256': sha})


@router.get('/v1/admin/audit')
def project_audit(user: dict = Depends(require_role('administrator')), after: int = Query(0, ge=0)):
    with tenant_session(read_only=True) as session:
        return {'events': rows(session, 'SELECT sequence,id,actor_sub,action,subject_id,occurred_at,previous_hash,'
                               'entry_hash,canonical_payload FROM audit_events WHERE sequence>:after ORDER BY sequence LIMIT 100',
                               after=after)}


@router.get('/v1/cases/{cid}/records/{collection}')
def page_records(cid: UUID, collection: str, user: dict = Depends(verified_identity),
                 cursor: UUID | None = None, limit: int = Query(100, ge=1, le=100)):
    if collection not in TABLES:
        fail('COLLECTION_NOT_FOUND', 404)
    with tenant_session(read_only=True) as session:
        access(session, cid, user)
        cols = 'id,source_id,sha256,mime,size_bytes,doc_version,retrieved_at' if collection == 'documents' else '*'
        found = rows(session, f'SELECT {cols} FROM {collection} WHERE case_id=:cid '  # noqa: S608  # nosec B608
                     'AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT :limit',
                     cid=str(cid), cursor=str(cursor) if cursor else None, limit=limit)
        return {'records': found, 'next_cursor': str(found[-1]['id']) if len(found) == limit else None}
