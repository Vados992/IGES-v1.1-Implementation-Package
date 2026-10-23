"""Live official sources in a fresh CI database; no synthetic records or market credentials."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import verified_identity
from app.database import tenant_session
from app.external_catalog import DATASETS
from app.external_persistence import store_external
from app.external_sources import fetch_external
from app.main import app
from app.verify_integrity import verify_integrity


async def main():
    if os.getenv("CI") != "true" and os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Live CI validator is restricted to explicitly disposable CI")
    root = Path("/receipts")
    root.mkdir(parents=True, exist_ok=True)
    receipts = []
    failures = []
    for dataset, spec in DATASETS.items():
        if spec.provider == "ALPACA" or spec.provider.startswith("UA_"):
            continue  # Market credentials are never silently substituted or requested from CI secrets.
        try:
            snapshot = await fetch_external(dataset, {}, limit=5)
            if not snapshot.records:
                raise ValueError("EXPECTED_REFERENCE_QUERY_RECORDS")
            with tenant_session() as session:
                saved = store_external(session, snapshot, "EXPLICIT_CI_REAL_PUBLIC_SOURCE_IMPORT")
            receipt = {
                "dataset": dataset,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "provider": spec.provider,
                "content_sha256": snapshot.sha256,
                "request_sha256": snapshot.request_sha256,
                "evidence_id": saved["evidence_id"],
                "records": len(snapshot.records),
                "has_more": snapshot.has_more,
                "transport": snapshot.transport,
                "scope": spec.limitations,
            }
            # Public artifacts contain metadata/hashes/counts, never property/licensed original bytes or complete records.
            receipts.append(receipt)
            (root / (dataset + ".json")).write_text(json.dumps(receipt, indent=2))
            print(json.dumps(receipt), flush=True)
        except Exception as error:
            failures.append({"dataset": dataset, "error_class": type(error).__name__})
            print(json.dumps(failures[-1]), flush=True)
    integrity = verify_integrity()
    app.dependency_overrides[verified_identity] = lambda: {
        "sub": "EXPLICIT_CI_SOURCE_READER",
        "roles": ["reader"],
    }
    try:
        with TestClient(app) as client:
            for receipt in receipts:
                response = client.get(f"/v1/sources/batches/{receipt['evidence_id']}/records?limit=100")
                response.raise_for_status()
                if not response.json()["records"] or any(
                    r["provenance_state"] != "UNASSESSED" for r in response.json()["records"]
                ):
                    raise ValueError("LIVE_API_RECORD_MISMATCH")
            denied = client.post(
                "/v1/sources/ingest",
                json={"dataset": "fdic_institutions"},
                headers={"Idempotency-Key": uuid4().hex},
            )
            if denied.status_code != 403:
                raise ValueError("READ_ROLE_MUST_NOT_INGEST")
    finally:
        app.dependency_overrides.clear()
    report = {
        "datasets_passed": len(receipts),
        "datasets_failed": failures,
        "records_imported": sum(r["records"] for r in receipts),
        "integrity": integrity,
        "market_data_http": "NOT_RUN_CREDENTIALS_ABSENT; actual MCP bridge checked separately",
        "publication": "NOT_ATTEMPTED_NO_REAL_HUMAN_APPROVALS",
    }
    (root / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
