import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.verify_integrity import verify_audit_rows


def audit_row():
    row = {"id": uuid4(), "project_id": uuid4(), "sequence": 1,
           "actor_sub": "actor", "action": "test", "subject_id": "subject",
           "occurred_at": datetime(2026, 10, 20, tzinfo=timezone.utc), "previous_hash": "0" * 64}
    payload = {"id": str(row["id"]), "project": str(row["project_id"]), "sequence": 1,
               "actor": row["actor_sub"], "action": row["action"], "subject": row["subject_id"],
               "timestamp": row["occurred_at"].isoformat()}
    row["canonical_payload"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    row["entry_hash"] = hashlib.sha256((row["previous_hash"] + row["canonical_payload"]).encode()).hexdigest()
    return row


def test_valid_chain_can_be_recomputed():
    assert verify_audit_rows([audit_row()]) == 1


@pytest.mark.parametrize("field,value", [("actor_sub", "other actor"), ("sequence", 2),
                                         ("entry_hash", "a" * 64), ("previous_hash", "b" * 64)])
def test_tampered_audit_is_rejected(field, value):
    row = audit_row()
    row[field] = value
    with pytest.raises(ValueError, match="integrity"):
        verify_audit_rows([row])
