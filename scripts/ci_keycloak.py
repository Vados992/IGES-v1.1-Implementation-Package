"""Actual Keycloak MFA/PKCE test on disposable GitHub infrastructure; never the owner's IdP."""
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from scripts.windows_pilot import ROOT, STATE, certificate, realm
from scripts import keycloak_validate


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)  # noqa: S603


def main():
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.name == 'nt' or (STATE / 'settings.json').exists():
        raise RuntimeError('This test only creates a new isolated Linux GitHub Actions IdP')
    STATE.mkdir(parents=True)
    config = {'project_id': str(uuid4()), 'operator_password': secrets.token_urlsafe(32),
              'bootstrap_password': secrets.token_urlsafe(32)}
    (STATE / 'settings.json').write_text(json.dumps(config))
    certificate()
    profile = ROOT / 'iges-ci-realm.json'
    profile.write_text(json.dumps(realm(config)))
    env_file = STATE / 'idp-ci.env'
    env_file.write_text('KC_BOOTSTRAP_ADMIN_USERNAME=iges-admin\nKC_BOOTSTRAP_ADMIN_PASSWORD=' + config['bootstrap_password'] + '\n')
    name = 'iges-ci-idp-' + uuid4().hex[:10]
    api = None
    try:
        run(['docker', 'run', '-d', '--name', name, '-p', '127.0.0.1:8443:8443', '--env-file', str(env_file),
             '-v', f'{STATE / "server.pem"}:/cert/server.pem:ro', '-v', f'{STATE / "server-key.pem"}:/cert/server-key.pem:ro',
             '-v', f'{profile}:/opt/keycloak/data/import/iges.json:ro', 'quay.io/keycloak/keycloak:26.8.1',
             'start-dev', '--hostname=https://localhost:8443', '--http-enabled=false', '--cache=local',
             '--https-certificate-file=/cert/server.pem', '--https-certificate-key-file=/cert/server-key.pem', '--import-realm'])
        context = ssl.create_default_context(cafile=str(STATE / 'ca.pem'))
        with httpx.Client(verify=context, timeout=3) as client:
            for _ in range(180):
                try:
                    client.get('https://localhost:8443/realms/iges/.well-known/openid-configuration').raise_for_status()
                    break
                except httpx.HTTPError:
                    time.sleep(1)
            else:
                raise RuntimeError('Isolated Keycloak startup failed')
        environment = {**os.environ, 'IGES_PUBLIC_PROJECT_ID': config['project_id'],
            'IGES_OIDC_ISSUER': 'https://localhost:8443/realms/iges', 'IGES_OIDC_AUDIENCE': 'iges-api',
            'IGES_OIDC_JWKS_URL': 'https://localhost:8443/realms/iges/protocol/openid-connect/certs',
            'IGES_OIDC_CA_FILE': str(STATE / 'ca.pem'), 'IGES_OIDC_REQUIRE_MFA': 'true'}
        with (ROOT / 'ci-api.log').open('w') as log:
            api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',  # noqa: S603
                '--port', '8444', '--no-access-log', '--ssl-certfile', str(STATE / 'server.pem'), '--ssl-keyfile', str(STATE / 'server-key.pem')],
                env=environment, stdout=log, stderr=subprocess.STDOUT)
        with httpx.Client(verify=context, timeout=3) as client:
            for _ in range(30):
                try:
                    client.get('https://localhost:8444/healthz').raise_for_status()
                    break
                except httpx.HTTPError:
                    time.sleep(1)
            else:
                raise RuntimeError('Isolated API startup failed')
        receipts = []
        for client_id, redirect in [('iges-desktop', 'http://127.0.0.1:8765/callback'),
                                    ('iges-web', 'https://localhost:8444/workspace')]:
            keycloak_validate.main(client_id, redirect)
            receipts.append(json.loads((ROOT / 'mfa-validation.json').read_text()))
        Path('work/ci-mfa-receipt.json').write_text(json.dumps(receipts, indent=2))
    except Exception:
        logs = run(['docker', 'logs', '--tail', '50', name])
        # No password, auth codes, tokens or request bodies are emitted by these server logs.
        print(logs.stdout)
        raise
    finally:
        if api:
            api.terminate()
            api.wait(timeout=20)
        run(['docker', 'rm', '-f', name])


if __name__ == '__main__':
    main()
