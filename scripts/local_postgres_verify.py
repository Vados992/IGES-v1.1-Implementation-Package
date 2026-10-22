"""Run tests against a new isolated native PostgreSQL cluster; never reuse pilot data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from uuid import uuid4

from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True,  # noqa: S603
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pg-bin', type=Path, required=True)
    parser.add_argument('--port', type=int, default=55434)
    parser.add_argument('--keep-running', action='store_true')
    args = parser.parse_args()
    suffix = '.exe' if os.name == 'nt' else ''
    def pg(name):
        return args.pg_bin / (name + suffix)
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            raise RuntimeError('Validation port already occupied; refusing to touch it')
    state = ROOT / 'work' / ('pg-validation-' + uuid4().hex)
    state.mkdir(parents=True)
    admin_password, runtime_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    project = str(uuid4())
    password = state / 'init-password'
    password.write_text(admin_password, encoding='utf-8')
    try:
        run([pg('initdb'), '-D', state / 'data', '-U', 'postgres', '--pwfile', password,
             '--encoding=UTF8', '--locale=C', '--auth-host=scram-sha-256', '--auth-local=scram-sha-256'],
            stdout=subprocess.DEVNULL)
    finally:
        password.unlink(missing_ok=True)
    with (state / 'data/postgresql.conf').open('a') as handle:
        handle.write(f"\nlisten_addresses='127.0.0.1'\nport={args.port}\n")
    run([pg('pg_ctl'), '-D', state / 'data', '-l', state / 'postgres.log', '-w', 'start'], stdout=subprocess.DEVNULL)
    environment = {**os.environ, 'PGPASSWORD': admin_password}
    psql = [pg('psql'), '-h', '127.0.0.1', '-p', str(args.port), '-U', 'postgres', '-v', 'ON_ERROR_STOP=1']
    try:
        run([*psql, '-d', 'postgres', '-c', 'CREATE DATABASE iges'], env=environment, stdout=subprocess.DEVNULL)
        run([*psql, '-d', 'postgres', '-c', 'CREATE DATABASE iges_restore'], env=environment, stdout=subprocess.DEVNULL)
        sql = f"\\set runtime_password '{runtime_password}'\n\\set project_id '{project}'\n"
        sql += (ROOT / 'db/init/01_schema.template').read_text()
        for migration in sorted((ROOT / 'db/migrations').glob('*.sql')):
            sql += '\n' + migration.read_text()
        run([*psql, '-d', 'iges', '--single-transaction'], input=sql, text=True, env=environment,
            stdout=subprocess.DEVNULL)
        def url(user, credential):
            return URL.create('postgresql+psycopg', username=user, password=credential, host='127.0.0.1',
                              port=args.port, database='iges').render_as_string(hide_password=False)
        environment.update(IGES_DATABASE_URL=url('iges_runtime', runtime_password),
                           IGES_TEST_ADMIN_URL=url('postgres', admin_password), IGES_PUBLIC_PROJECT_ID=project)
        (state / 'test-environment.json').write_text(json.dumps({k: v for k, v in environment.items() if k.startswith('IGES_')}))
        # Credentials stay in ignored work/ and are never printed or uploaded as CI artifacts.
        result = subprocess.run([sys.executable, '-u', '-m', 'pytest', '-q'], env=environment, cwd=ROOT,  # noqa: S603
                                capture_output=True, text=True, check=False)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        result.check_returncode()
        result = run([sys.executable, '-m', 'app.verify_integrity'], env=environment, cwd=ROOT,
                     capture_output=True, text=True)
        print(result.stdout, flush=True)
        print(json.dumps({'status': 'PASSED', 'cluster': str(state), 'port': args.port}))
    finally:
        if not args.keep_running:
            run([pg('pg_ctl'), '-D', state / 'data', '-w', 'stop'], stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
