"""Real document/OCR pipeline; explicit CI identities, no invented human approvals."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4
from fastapi.testclient import TestClient
from app.auth import verified_identity
from app.extraction import command
from app.main import app
from app.process_documents import process_once
from app.verify_integrity import verify_integrity


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    if os.getenv('IGES_TEST_ADMIN_URL') != 'isolated-ci-intake-only':
        raise RuntimeError('Only run in a disposable CI environment')
    source_dir = Path(os.environ['IGES_TEST_SOURCE_DIR'])
    raw = (source_dir / 'rfc9457.pdf').read_bytes()
    receipt = json.loads((source_dir / 'receipt.json').read_text())
    require(hashlib.sha256(raw).hexdigest() == receipt['sha256'], 'Source receipt mismatch')
    identity = {'sub': 'CI_INTAKE_TEST_IDENTITY', 'roles': ['analyst', 'editor']}
    app.dependency_overrides[verified_identity] = lambda: identity
    try:
        with TestClient(app) as client:
            revision = None
            def post(path, body=None, content=None):
                nonlocal revision
                headers = {'Idempotency-Key': uuid4().hex}
                if revision is not None:
                    headers['If-Match'] = f'"{revision}"'
                result = client.post(path, json=body, headers=headers) if content is None else client.post(path, content=content, headers=headers)
                require(result.status_code == 201, result.text)
                data = result.json()
                revision = data['case_revision']
                return data
            case = post('/v1/cases', {'title': 'RFC 9457 primary-document intake validation',
                'scope': 'Verify document intake, page extraction and quotations; no substantive conclusion is published.',
                'period_from': '2023-07-01', 'period_to': '2023-07-31', 'jurisdictions': ['International']})
            base = '/v1/cases/' + case['id']
            source = post(base + '/sources', {'title': 'RFC 9457: Problem Details for HTTP APIs',
                'publisher': 'RFC Editor / IETF', 'url': receipt['source_url'], 'published_at': None,
                'language': 'en', 'primacy': 'primary', 'independence_group': 'ietf-rfc9457',
                'provenance_basis': 'Direct RFC Editor HTTPS origin; exact bytes and receipt retained. Header states July 2023; exact day is unknown.'})
            doc = post(base + '/documents?source_id=' + source['id'], content=raw)
            require(process_once() == 1, 'Worker did not process PDF')
            revision = client.get(base).json()['case_revision']
            pages = client.get(base + '/documents/' + doc['id'] + '/pages').json()
            require(pages['processing'][0]['status'] == 'READY', 'PDF scan/extraction failed')
            require('Problem Details' in pages['pages'][0]['text_content'], 'Page text missing')
            require(client.get(base + '/documents/' + doc['id'] + '/original').content == raw, 'Original changed')
            derived_source = post(base + '/sources', {'title': 'Page 1 rendering derived from RFC 9457',
                'publisher': 'IGES isolated CI rendering process', 'url': receipt['source_url'], 'language': 'en',
                'primacy': 'derivative', 'independence_group': 'ietf-rfc9457',
                'provenance_basis': 'Rendered from the retained primary PDF using Poppler; not an independent source. Original SHA-256: ' + receipt['sha256']})
            with tempfile.TemporaryDirectory() as directory:
                png = Path(directory) / 'page'
                subprocess.run([command('pdftoppm'), '-f', '1', '-l', '1', '-singlefile', '-scale-to', '2400',  # noqa: S603
                                '-png', str(source_dir / 'rfc9457.pdf'), str(png)], check=True)  # noqa: S603
                image = post(base + '/documents?source_id=' + derived_source['id'], content=png.with_suffix('.png').read_bytes())
            require(process_once() == 1, 'Worker did not process image')
            revision = client.get(base).json()['case_revision']
            image_pages = client.get(base + '/documents/' + image['id'] + '/pages').json()
            require(image_pages['processing'][0]['status'] == 'READY', 'OCR failed')
            require(image_pages['pages'][0]['method'] == 'tesseract-tsv', 'Real OCR engine not used')
            require(image_pages['pages'][0]['confidence'] is not None, 'OCR confidence missing')
            require('problem' in image_pages['pages'][0]['text_content'].lower(), 'OCR source text missing')
            require(client.get(base + '/search?q=Problem').json()['records'], 'Search returned no locators')
            # Scanner fixture only; never treated as a source or a finding.
            test_source = post(base + '/sources', {'title': 'EXPLICIT EICAR SCANNER TEST FIXTURE',
                'publisher': 'Isolated CI test harness', 'url': 'https://www.eicar.org/download-anti-malware-testfile/',
                'language': 'en', 'primacy': 'derivative', 'independence_group': 'EXPLICIT_TEST_FIXTURE',
                'provenance_basis': 'Constructed standard scanner marker for a negative security test; not fetched factual evidence and never published.'})
            eicar = b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
            bad = post(base + '/documents?source_id=' + test_source['id'], content=eicar)
            require(process_once() == 1, 'Worker did not inspect scanner marker')
            status = client.get(base + '/documents/' + bad['id'] + '/pages').json()['processing'][0]['status']
            require(status == 'QUARANTINED', 'EICAR not quarantined')
            require(client.get(base + '/documents/' + bad['id'] + '/original').status_code == 409, 'Unsafe original downloadable')
            print(json.dumps({'source_receipt': receipt, 'pdf_pages': len(pages['pages']),
                              'ocr_confidence': image_pages['pages'][0]['confidence'], 'eicar_quarantined': True,
                              'identities': 'EXPLICIT_CI_TEST_IDENTITIES', 'publication': 'NOT_ATTEMPTED_NO_HUMAN_APPROVALS',
                              'integrity': verify_integrity()}))
    finally:
        app.dependency_overrides.clear()


if __name__ == '__main__':
    main()
