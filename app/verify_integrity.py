"""Read-only integrity check; hashes never establish source truth or external anchoring."""
from __future__ import annotations

import hashlib
import json
from datetime import timezone

from sqlalchemy import text

from app.database import tenant_session


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


def verify_integrity() -> dict:
    with tenant_session(read_only=True, repeatable_read=True) as session:
        # A single coherent snapshot while other writers continue.
        evidence = session.execute(text("SELECT id,content_sha256,raw_bytes FROM evidence")).mappings().all()
        for row in evidence:
            if hashlib.sha256(bytes(row["raw_bytes"])).hexdigest() != row["content_sha256"]:
                raise ValueError(f"evidence digest mismatch: {row['id']}")
        rows = session.execute(text("SELECT * FROM audit_events ORDER BY sequence")).mappings().all()
        count = verify_audit_rows(rows)
    return {"evidence_hashes_checked": len(evidence), "audit_entries_checked": count,
            "status": "INTERNALLY_CONSISTENT", "externally_anchored": False}


if __name__ == "__main__":
    print(json.dumps(verify_integrity(), indent=2))
