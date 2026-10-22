"""Loopback UI test harness for the disposable validation cluster, never the working pilot."""
import argparse
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = args.env_file.resolve()
    if not path.is_relative_to(root / 'work'):
        raise RuntimeError('Test environment must be in ignored work/')
    environment = json.loads(path.read_text())
    url = make_url(environment['IGES_TEST_ADMIN_URL'])
    if url.host != '127.0.0.1' or url.port != 55434:
        raise RuntimeError('Refusing to bind test authentication to a non-test database')
    os.environ.update(environment)
    from sqlalchemy import create_engine
    from app.migrate import upgrade
    test_engine = create_engine(url)
    with test_engine.begin() as connection:
        upgrade(connection)
    test_engine.dispose()
    from fastapi import Request, HTTPException
    from app.auth import verified_identity
    from app.main import app
    import uvicorn
    def test_identity(request: Request):
        if request.headers.get('authorization') != 'Bearer EXPLICIT-LOCAL-UI-TEST-TOKEN':
            raise HTTPException(401, 'TEST_IDENTITY_REQUIRED')
        return {'sub': 'EXPLICIT_UI_TEST_ACTOR', 'project_id': environment['IGES_PUBLIC_PROJECT_ID'],
                'roles': ['analyst', 'editor']}
    app.dependency_overrides[verified_identity] = test_identity
    uvicorn.run(app, host='127.0.0.1', port=8097, access_log=False)


if __name__ == '__main__':
    main()
