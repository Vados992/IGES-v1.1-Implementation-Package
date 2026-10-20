"""Parameterized writes with immutable source snapshots and hash-chain audit."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.worldbank import Snapshot


def append_audit(session: Session, actor: str, action: str, subject: str) -> str:
    project_id = str(settings.project_id)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"iges-audit:{project_id}"},
    )
    prior = session.execute(
        text("SELECT sequence,entry_hash FROM audit_events WHERE project_id=:pid "
             "ORDER BY sequence DESC LIMIT 1"),
        {"pid": project_id},
    ).mappings().first()
    previous = prior["entry_hash"] if prior else "0" * 64
    sequence = prior["sequence"] + 1 if prior else 1
    event_id = str(uuid4())
    at = datetime.now(timezone.utc)
    canon = json.dumps(
        {"id": event_id, "project": project_id, "sequence": sequence, "actor": actor,
         "action": action, "subject": subject, "timestamp": at.isoformat()},
        sort_keys=True, separators=(",", ":"),
    )
    digest = hashlib.sha256((previous + canon).encode("utf-8")).hexdigest()
    session.execute(
        text("INSERT INTO audit_events "
             "(id,project_id,sequence,actor_sub,action,subject_id,occurred_at,previous_hash,entry_hash,canonical_payload) "
             "VALUES (:id,:pid,:sequence,:actor,:action,:subject,:at,:previous,:digest,:canon)"),
        {"id": event_id, "pid": project_id, "actor": actor,
         "action": action, "subject": subject, "at": at,
         "previous": previous, "digest": digest, "sequence": sequence, "canon": canon},
    )
    return event_id


def store_snapshot(session: Session, snapshot: Snapshot, actor: str) -> tuple[str, int, bool]:
    pid = str(settings.project_id)
    evidence_id = str(uuid4())
    inserted_id = session.execute(
        text("INSERT INTO evidence "
             "(id,project_id,provider,source_url,content_sha256,raw_bytes) "
             "VALUES (:id,:pid,'WORLD_BANK',:url,:sha,:raw) "
             "ON CONFLICT (project_id,provider,content_sha256) DO NOTHING RETURNING id"),
        {"id": evidence_id, "pid": pid, "url": snapshot.url,
         "sha": snapshot.sha256, "raw": snapshot.raw},
    ).scalar_one_or_none()
    if inserted_id is None:
        prior = session.execute(
            text("SELECT id FROM evidence WHERE project_id=:pid "
                 "AND provider='WORLD_BANK' AND content_sha256=:sha"),
            {"pid": pid, "sha": snapshot.sha256},
        ).scalar_one()
        return str(prior), 0, False
    for row in snapshot.observations:
        session.execute(
            text("INSERT INTO observations "
                 "(project_id,evidence_id,country_code,indicator_code,period,numeric_value,"
                 "observation_status,source_locator) "
                 "VALUES (:pid,:eid,:country,:indicator,:year,:value,:status,:locator)"),
            {"pid": pid, "eid": str(inserted_id), "country": row.country,
             "indicator": row.indicator, "year": row.year,
             "value": row.value, "status": row.status, "locator": row.locator},
        )
    append_audit(session, actor, "WORLD_BANK_SNAPSHOT_RECEIVED", str(inserted_id))
    return str(inserted_id), len(snapshot.observations), True
