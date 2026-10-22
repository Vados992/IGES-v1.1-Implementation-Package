"""Bind all workspace record contents to the audit chain, without storing private text in the log."""
import hashlib
import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.config import settings
from app.persistence import append_audit

SEALED_TABLES = {'cases', 'case_members', 'claims', 'hypotheses', 'sources', 'documents', 'document_pages',
                 'document_processing', 'evidence_items', 'entities', 'relationships', 'review_assignments',
                 'assessments', 'publication_gates', 'responses', 'publications', 'entity_resolutions', 'case_revisions', 'case_member_revocations'}


def normalize(values):
    normalized = {}
    for key, value in values.items():
        if isinstance(value, (bytes, memoryview)):
            value = {'bytes_sha256': hashlib.sha256(bytes(value)).hexdigest()}
        elif key in {'body', 'receipt', 'locator'} and isinstance(value, str):
            value = json.loads(value)
        normalized[key] = jsonable_encoder(value)
    return normalized


def seal(session, table, values):
    if table not in SEALED_TABLES:
        return
    canonical = json.dumps(normalize(values), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    sha = hashlib.sha256(canonical.encode()).hexdigest()
    session.execute(text('INSERT INTO record_seals(project_id,table_name,object_id,canonical_record,record_sha256) '
                         'VALUES(:pid,:table,:id,:canonical,:sha)'),
                    {'pid': str(settings.project_id), 'table': table, 'id': values['id'], 'canonical': canonical, 'sha': sha})
    append_audit(session, values['created_by'], 'RECORD_SEALED', f"{table}:{values['id']}:{sha}")


def verify_workspace(session, audit):
    subjects = {(r['action'], r['subject_id']) for r in audit}
    seals = session.execute(text('SELECT * FROM record_seals')).mappings().all()
    seen = set()
    for record in seals:
        table = record['table_name']
        if table not in SEALED_TABLES:
            raise ValueError('Unrecognized sealed table')
        canonical = record['canonical_record']
        sha = hashlib.sha256(canonical.encode()).hexdigest()
        if sha != record['record_sha256'] or ('RECORD_SEALED', f"{table}:{record['object_id']}:{sha}") not in subjects:
            raise ValueError('Record seal not bound to audit chain')
        stored = session.execute(text(f'SELECT * FROM {table} WHERE id=:id'),  # noqa: S608  # nosec B608
                                 {'id': record['object_id']}).mappings().one()
        expected = json.loads(canonical)
        actual = normalize({key: stored[key] for key in expected})
        if actual != expected:
            raise ValueError(f"Record content changed: {table}:{record['object_id']}")
        seen.add((table, str(record['object_id'])))
    for table in SEALED_TABLES:
        condition = ' WHERE case_id IS NOT NULL' if table == 'claims' else ''
        ids = session.execute(text(f'SELECT id FROM {table}{condition}')).scalars().all()  # noqa: S608  # nosec B608
        if any((table, str(oid)) not in seen for oid in ids):
            raise ValueError(f'Unaudited workspace insert: {table}')
    documents = session.execute(text('SELECT id,sha256,raw_bytes FROM documents')).mappings().all()
    for doc in documents:
        if hashlib.sha256(bytes(doc['raw_bytes'])).hexdigest() != doc['sha256']:
            raise ValueError('Document integrity incident')
    events = session.execute(text('SELECT * FROM case_events ORDER BY case_id,revision')).mappings().all()
    counters = {}
    for event in events:
        cid = str(event['case_id'])
        counters[cid] = counters.get(cid, 0) + 1
        sha = hashlib.sha256(event['canonical_payload'].encode()).hexdigest()
        if (event['revision'] != counters[cid] or sha != event['payload_sha256']
                or json.loads(event['canonical_payload']) != event['payload']
                or (event['action'], f"{cid}:{event['revision']}:{sha}") not in subjects):
            raise ValueError('Workspace revision or audit linkage failed')
    for pub in session.execute(text('SELECT id,canonical_manifest,manifest_hash FROM publications')).mappings():
        sha = hashlib.sha256(pub['canonical_manifest'].encode()).hexdigest()
        if sha != pub['manifest_hash'] or ('PUBLICATION_MANIFEST', f"{pub['id']}:{sha}") not in subjects:
            raise ValueError('Publication manifest or audit linkage failed')
    return {'workspace_records_checked': len(seals), 'document_hashes_checked': len(documents),
            'case_revisions_checked': len(events)}
