"""Fetch an actual RFC Editor PDF; fail without substitutes."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import httpx

URL = 'https://www.rfc-editor.org/rfc/rfc9457.pdf'


def main():
    with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
        response = client.get(URL)
        response.raise_for_status()
    raw = response.content
    if not raw.startswith(b'%PDF-') or len(raw) > 8388608:
        raise ValueError('Official PDF unavailable or invalid')
    target = Path('work/intake-source')
    target.mkdir(parents=True, exist_ok=True)
    (target / 'rfc9457.pdf').write_bytes(raw)
    receipt = {'source_url': URL, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
               'retrieved_at': datetime.now(timezone.utc).isoformat(), 'meaning': 'Actual primary document'}
    (target / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
