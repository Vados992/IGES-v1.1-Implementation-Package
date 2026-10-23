"""Loopback, explicit read-only UI acceptance harness for this task's actual source corpus."""

import argparse
import json
import os
from pathlib import Path
import re

from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only-review", action="store_true", required=True)
    parser.parse_args()
    state = Path(__file__).resolve().parents[1] / "work/source-corpus"
    environment = json.loads((state / "environment.json").read_text())
    url = make_url(environment["IGES_DATABASE_URL"])
    if (
        url.host != "127.0.0.1"
        or url.port != 55434
        or not re.fullmatch(r"iges_sources_[a-f0-9]{32}", url.database)
    ):
        raise RuntimeError("Isolated source corpus required; installed pilot is not permitted")
    os.environ.update(environment)
    from fastapi import HTTPException, Request
    from app.auth import verified_identity
    from app.main import app
    import uvicorn

    def test_reader(request: Request):
        if request.headers.get("authorization") != "Bearer EXPLICIT-LOCAL-SOURCE-REVIEW":
            raise HTTPException(401, "EXPLICIT_LOCAL_SOURCE_REVIEW_REQUIRED")
        return {
            "sub": "EXPLICIT_READ_ONLY_UI_REVIEW",
            "project_id": environment["IGES_PUBLIC_PROJECT_ID"],
            "roles": ["reader"],
        }

    app.dependency_overrides[verified_identity] = test_reader
    uvicorn.run(app, host="127.0.0.1", port=8098, access_log=False)


if __name__ == "__main__":
    main()
