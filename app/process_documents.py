"""Durable PostgreSQL-backed intake worker. No parsers run in the API process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess  # nosec B404
import sys
import tempfile
import time

from sqlalchemy import text

from app.database import tenant_session
from app.persistence import append_audit
from app.workflow import rows, insert, content_event


def process_once():
    processed = 0
    with tenant_session() as session:
        pending = rows(session, "SELECT d.* FROM documents d WHERE coalesce((SELECT p.status FROM document_processing p "
                       "WHERE p.document_id=d.id ORDER BY created_at DESC,id DESC LIMIT 1),'RETRY_REQUESTED')='RETRY_REQUESTED' "
                       'ORDER BY retrieved_at LIMIT 10')
        for doc in pending:
            acquired = session.execute(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))'),
                                       {'key': 'document:' + str(doc['id'])}).scalar_one()
            if not acquired:
                continue
            latest = rows(session, 'SELECT status FROM document_processing WHERE document_id=:id '
                          'ORDER BY created_at DESC,id DESC LIMIT 1', id=doc['id'])
            if latest and latest[0]['status'] != 'RETRY_REQUESTED':
                continue
            actor = {'sub': 'IGES_DOCUMENT_WORKER'}
            receipt = {'code': 'EXTRACTION_FAILED'}
            status = 'FAILED'
            result = None
            with tempfile.TemporaryDirectory(prefix='iges-intake-') as directory:
                path = Path(directory) / 'original'
                path.write_bytes(bytes(doc['raw_bytes']))
                if hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
                    receipt = {'code': 'HASH_MISMATCH'}
                else:
                    try:
                        child_env = {k: v for k, v in os.environ.items() if k.upper() in
                                     {'PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'LANG', 'IGES_CLAMSCAN',
                                      'IGES_TESSERACT', 'IGES_PDFTOPPM', 'IGES_OCR_LANGUAGES',
                                      'IGES_CLAMD_HOST', 'IGES_CLAMD_PORT'}}
                        child = subprocess.run([sys.executable, '-m', 'app.extraction', str(path)],  # noqa: S603  # nosec B603
                            capture_output=True, timeout=180, check=False, env=child_env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                        if len(child.stdout) > 24_000_000:
                            raise ValueError('WORKER_OUTPUT_LIMIT')
                        result = json.loads(child.stdout)
                        if child.returncode == 0 and result.get('scanner', {}).get('sha256') == doc['sha256']:
                            status = 'READY'
                            receipt = {'mime': result['mime'], 'scanner': result['scanner'],
                                       'page_count': len(result['pages']), 'extractor': 'iges-extraction/1'}
                        else:
                            receipt = {'code': 'SCAN_OR_EXTRACTION_FAILED'}
                            if result.get('code') == 'MALWARE_OR_SCAN_LIMIT':
                                status = 'QUARANTINED'
                    except (subprocess.SubprocessError, ValueError, OSError):
                        receipt = {'code': 'WORKER_FAILED_OR_TIMED_OUT'}
            # Lock the case only while committing the extraction; publication cannot race a content change.
            session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                            {'key': 'case:' + str(doc['case_id'])})
            if status == 'READY':
                for number, page in enumerate(result['pages'], 1):
                    insert(session, 'document_pages', doc['case_id'], actor, None,
                           document_id=str(doc['id']), page=number, text_content=page['text'],
                           confidence=page['confidence'], method=page['method'],
                           locator=json.dumps({'archive_member': page.get('member'),
                                               'page_kind': 'physical' if page['method'] in {'pdf-text', 'tesseract-tsv'} else 'logical'}),
                           content_sha256=hashlib.sha256(page['text'].encode()).hexdigest())
            insert(session, 'document_processing', doc['case_id'], actor, None,
                   document_id=str(doc['id']), status=status, receipt=json.dumps(receipt))
            content_event(session, doc['case_id'], actor, 'DOCUMENT_' + status,
                          {'document_id': str(doc['id']), 'sha256': doc['sha256'], 'receipt': receipt})
            append_audit(session, actor['sub'], 'DOCUMENT_PROCESSING_FINISHED', str(doc['id']) + ':' + status)
            processed += 1
            break  # Release case/audit locks before acquiring a different case in another transaction.
    return processed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    once = parser.parse_args().once
    while True:
        print(json.dumps({'processed': process_once()}), flush=True)
        if once:
            break
        time.sleep(3)
