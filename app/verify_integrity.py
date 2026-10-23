"""Read-only integrity check; hashes never establish source truth or external anchoring."""
from __future__ import annotations

import hashlib
import json
import re
import argparse
from datetime import timezone
from pathlib import Path

from sqlalchemy import text

from app.database import tenant_session, check_database
from app.worldbank import parse_snapshot
from app.usaspending import parse_awards, canonical_request
from app.record_integrity import verify_workspace
from app.external_catalog import PROVIDERS
from app.external_persistence import verify_external


def verify_audit_rows(rows) -> int:
    previous = "0" * 64
    for sequence, row in enumerate(rows, 1):
        payload = json.loads(row["canonical_payload"])
        digest = hashlib.sha256((previous + row["canonical_payload"]).encode("utf-8")).hexdigest()
        expected = {"id": str(row["id"]), "project": str(row["project_id"]),
                    "sequence": sequence, "actor": row["actor_sub"], "action": row["action"],
                    "subject": row["subject_id"], "timestamp": row["occurred_at"].astimezone(timezone.utc).isoformat()}
        if (row["sequence"] != sequence or row["previous_hash"] != previous
                or row["entry_hash"] != digest or payload != expected):
            raise ValueError(f"audit integrity failed at sequence {sequence}")
        previous = digest
    return len(rows)


def verify_integrity(export_dir: Path | None = None) -> dict:
    with tenant_session(read_only=True, repeatable_read=True) as session:
        check_database(session)
        # A single coherent snapshot while other writers continue.
        evidence = session.execute(text(
            "SELECT id,provider,content_sha256,request_sha256,source_request,raw_bytes,source_url,retrieved_at,media_type FROM evidence"
        )).mappings().all()
        for row in evidence:
            if hashlib.sha256(bytes(row["raw_bytes"])).hexdigest() != row["content_sha256"]:
                raise ValueError(f"evidence digest mismatch: {row['id']}")
            if row['provider'] in PROVIDERS:
                continue
            if row["provider"] == "USA_SPENDING":
                if hashlib.sha256(canonical_request(row["source_request"])).hexdigest() != row["request_sha256"]:
                    raise ValueError(f"request digest mismatch: {row['id']}")
                awards = parse_awards(bytes(row["raw_bytes"]), row["source_request"], row["source_url"])
                stored = session.execute(text(
                    "SELECT source_award_key,external_award_id,recipient_name,awarding_agency,funding_agency,"
                    "award_amount,source_locator FROM public_awards WHERE evidence_id=:eid"), {"eid": row["id"]}).all()
                expected = {(a.key, a.award_id, a.recipient, a.awarding_agency, a.funding_agency, a.amount, a.locator)
                            for a in awards.awards}
                if len(stored) != len(expected) or {tuple(a) for a in stored} != expected:
                    raise ValueError(f"award locator/value mismatch: {row['id']}")
                continue
            if row["provider"] != "WORLD_BANK":
                raise ValueError("unknown evidence provider")
            request_hash = hashlib.sha256(("GET " + row["source_url"]).encode()).hexdigest()
            if request_hash != row["request_sha256"]:
                raise ValueError(f"request digest mismatch: {row['id']}")
            request = re.fullmatch(
                r"https://api\.worldbank\.org/v2/country/([A-Z]{3})/indicator/([A-Z.0-9]+)"
                r"\?format=json&date=([0-9]{4}):([0-9]{4})&per_page=100", row["source_url"])
            if request is None:
                raise ValueError(f"unexpected source URL: {row['id']}")
            country, indicator, start, end = request.groups()
            snap = parse_snapshot(bytes(row["raw_bytes"]), row["source_url"], country, indicator, int(start), int(end))
            stored = session.execute(text(
                "SELECT country_code,indicator_code,period,numeric_value,observation_status,source_locator "
                "FROM observations WHERE evidence_id=:eid"), {"eid": row["id"]}).all()
            expected = {(o.country, o.indicator, o.year, o.value, o.status, o.locator) for o in snap.observations}
            if len(stored) != len(expected) or {tuple(o) for o in stored} != expected:
                raise ValueError(f"observation locator/value mismatch: {row['id']}")
        rows = session.execute(text("SELECT * FROM audit_events ORDER BY sequence")).mappings().all()
        count = verify_audit_rows(rows)
        workspace = verify_workspace(session, rows)
        external = verify_external(session, evidence, rows)
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        for row in evidence:
            if row['provider'] in PROVIDERS:
                continue  # Property/licensed/identity originals never enter the public-source export.
            (export_dir / f"{row['id']}.response.json").write_bytes(bytes(row["raw_bytes"]))
            receipt = {key: row[key] for key in ["provider", "content_sha256", "request_sha256", "source_request", "source_url"]}
            receipt.update(evidence_id=str(row["id"]), retrieved_at=row["retrieved_at"].isoformat())
            (export_dir / f"{row['id']}.receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return {**workspace, **external, "evidence_hashes_checked": len(evidence), "audit_entries_checked": count,
            "status": "INTERNALLY_CONSISTENT", "externally_anchored": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify schema permissions, both sources and audit history")
    parser.add_argument("--export-dir", type=Path, help="Optionally export verified public-source snapshots only")
    print(json.dumps(verify_integrity(parser.parse_args().export_dir), indent=2))
