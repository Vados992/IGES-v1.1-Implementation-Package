"""Actual Ukrainian source integration; public CI artifacts contain only counts and hashes."""

import asyncio
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import verified_identity
from app.database import tenant_session
from app.external_persistence import store_external, store_collection_attempt
from app.external_sources import fetch_external
from app.main import app
from app.verify_integrity import verify_integrity
from scripts.probe_nazk import probe


async def main():
    if os.getenv("CI") != "true":
        raise RuntimeError("Disposable CI database required")
    root = Path("/receipts")
    root.mkdir(parents=True, exist_ok=True)
    reports, failures = [], []
    plan = json.loads((Path(__file__).parent / "data_plans/ukraine_public_office.json").read_text())
    for item in plan:
        report = {"dataset": item["dataset"], "params": item["params"]}
        try:
            snap = await fetch_external(item["dataset"], item["params"])
            if not snap.records:
                raise ValueError("EMPTY_EXPECTED_OFFICIAL_ARCHIVE")
            with tenant_session() as session:
                saved = store_external(session, snap, "EXPLICIT_CI_UKRAINE_PUBLIC_SOURCE_CHECK")
                report.update(
                    status="IMPORTED",
                    evidence_id=saved["evidence_id"],
                    records=len(snap.records),
                    content_sha256=snap.sha256,
                    coverage=snap.coverage,
                )
                store_collection_attempt(session, report, "EXPLICIT_CI_UKRAINE_PUBLIC_SOURCE_CHECK")
        except Exception as error:
            report.update(status="FAILED", error_class=type(error).__name__)
            failures.append(report)
        reports.append(report)
        print(json.dumps(report), flush=True)
        await asyncio.sleep(10)
    # Access denial remains visible. It is not evidence of declaration ingestion or a passing adapter.
    availability = await probe(2024)
    app.dependency_overrides[verified_identity] = lambda: {
        "sub": "EXPLICIT_CI_UKRAINE_READER",
        "roles": ["reader"],
    }
    try:
        with TestClient(app) as client:
            coverage = client.get("/v1/sources/ukraine/coverage")
            coverage.raise_for_status()
            if coverage.json()["universe_complete"]:
                raise ValueError("UNSUPPORTED_COMPLETE_COVERAGE_CLAIM")
            # Search a real returned source name, not a synthetic person; do not log the name.
            with tenant_session(read_only=True) as session:
                from sqlalchemy import text

                name = session.execute(
                    text("SELECT body->>'name' FROM source_records WHERE body ? 'search_name' LIMIT 1")
                ).scalar_one_or_none()
            if name:
                found = client.get("/v1/sources/ukraine/search", params={"q": name[:100]})
                found.raise_for_status()
                if not found.json()["records"]:
                    raise ValueError("REAL_RECORD_SEARCH_FAILED")
    finally:
        app.dependency_overrides.clear()
    report = {
        "official_archives": reports,
        "failures": failures,
        "nazk_availability_only": availability,
        "integrity": verify_integrity(),
        "complete_politician_or_financial_coverage": False,
        "publication": "NOT_ATTEMPTED_NO_HUMAN_APPROVALS",
    }
    (root / "ukraine-summary.json").write_text(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
