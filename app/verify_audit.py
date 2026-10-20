"""Verify the append-only per-project hash chain within current DB state."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from app.database import tenant_session


def main():
    previous = "0" * 64
    with tenant_session() as session:
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
    print(f"PASS: validated {len(rows)} sequential audit events in pilot DB")


if __name__ == "__main__":
    main()
