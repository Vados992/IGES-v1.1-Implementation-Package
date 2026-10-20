"""Verify the append-only per-project hash chain within current DB state."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from app.database import tenant_session
from app.usaspending import canonical_request


def main():
    previous = "0" * 64
    with tenant_session() as session:
        snapshots = session.execute(
            text("SELECT id,provider,source_url,source_request,content_sha256,request_sha256,raw_bytes FROM evidence")
        ).mappings().all()
        for snap in snapshots:
            actual = hashlib.sha256(snap["raw_bytes"]).hexdigest()
            if actual != snap["content_sha256"]:
                raise AssertionError(f"original source payload changed: {snap['id']}")
            if snap["provider"] == "WORLD_BANK":
                key = ("GET " + snap["source_url"]).encode("utf-8")
            elif snap["provider"] == "USA_SPENDING":
                key = canonical_request(snap["source_request"])
            else:
                raise AssertionError("unknown source provider")
            if hashlib.sha256(key).hexdigest() != snap["request_sha256"]:
                raise AssertionError(f"source request changed: {snap['id']}")
        rows = session.execute(
            text("SELECT id,actor_sub,action,subject_id,occurred_at,previous_hash,entry_hash,"
                 "project_id FROM audit_events ORDER BY occurred_at,id")
        ).mappings().all()
        for row in rows:
            canonical = json.dumps(
                {"id": str(row["id"]), "project": str(row["project_id"]),
                 "actor": row["actor_sub"], "action": row["action"],
                 "subject": row["subject_id"], "timestamp": row["occurred_at"].isoformat()},
                sort_keys=True, separators=(",", ":"),
            )
            digest = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
            if row["previous_hash"] != previous or row["entry_hash"] != digest:
                raise AssertionError(f"audit chain mismatch at event {row['id']}")
            previous = digest
    print(f"PASS: validated {len(rows)} sequential audit events and {len(snapshots)} source hashes")


if __name__ == "__main__":
    main()
