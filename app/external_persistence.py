"""Append-only public-source batches, atomic deduplication and full raw-to-record replay."""

import hashlib
from uuid import uuid4

from sqlalchemy import text

from app.config import settings
from app.external_catalog import DATASETS, PROVIDERS
from app.external_sources import canonical, parse_external
from app.persistence import append_audit


def row_hash(record):
    return hashlib.sha256(canonical(record).encode()).hexdigest()


def store_external(session, snapshot, actor):
    spec = DATASETS[snapshot.query["dataset"]]
    pid = str(settings.project_id)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "source:" + snapshot.request_sha256},
    )
    eid = str(uuid4())
    inserted = session.execute(
        text(
            "INSERT INTO evidence(id,project_id,provider,source_url,content_sha256,request_sha256,source_request,raw_bytes,media_type) "
            "VALUES(:id,:pid,:provider,:url,:sha,:rsha,CAST(:query AS jsonb),:raw,:mime) "
            "ON CONFLICT(project_id,provider,content_sha256,request_sha256) DO NOTHING RETURNING id"
        ),
        {
            "id": eid,
            "pid": pid,
            "provider": spec.provider,
            "url": snapshot.url,
            "sha": snapshot.sha256,
            "rsha": snapshot.request_sha256,
            "query": canonical(snapshot.query),
            "raw": snapshot.raw,
            "mime": snapshot.media_type,
        },
    ).scalar_one_or_none()
    if inserted is None:
        prior = session.execute(
            text(
                "SELECT id FROM evidence WHERE provider=:provider AND request_sha256=:rsha AND content_sha256=:sha"
            ),
            {"provider": spec.provider, "rsha": snapshot.request_sha256, "sha": snapshot.sha256},
        ).scalar_one()
        return {
            "evidence_id": str(prior),
            "created": False,
            "records_inserted": 0,
            "returned_count": len(snapshot.records),
            "has_more": snapshot.has_more,
            "content_sha256": snapshot.sha256,
            "coverage": snapshot.coverage,
        }
    metadata = {
        "dataset": snapshot.query["dataset"],
        "query": snapshot.query,
        "transport": snapshot.transport,
        "documentation": spec.documentation,
        "sector": spec.sector,
        "coverage": snapshot.coverage,
        "meaning": "Source-attributed records, not independently reviewed findings; private research access only",
    }
    sha = row_hash(metadata)
    session.execute(
        text(
            "INSERT INTO source_batches(id,project_id,dataset,metadata,metadata_sha256) "
            "VALUES(:id,:pid,:dataset,CAST(:body AS jsonb),:sha)"
        ),
        {
            "id": eid,
            "pid": pid,
            "dataset": snapshot.query["dataset"],
            "body": canonical(metadata),
            "sha": sha,
        },
    )
    for record in snapshot.records:
        session.execute(
            text(
                "INSERT INTO source_records(project_id,evidence_id,source_key,body,source_locator,record_sha256) "
                "VALUES(:pid,:eid,:key,CAST(:body AS jsonb),:locator,:sha)"
            ),
            {
                "pid": pid,
                "eid": eid,
                "key": record["key"],
                "body": canonical(record["body"]),
                "locator": record["locator"],
                "sha": row_hash(record),
            },
        )
    append_audit(session, actor, "EXTERNAL_SOURCE_BATCH_RECEIVED", f"{eid}:{sha}")
    return {
        "evidence_id": eid,
        "created": True,
        "records_inserted": len(snapshot.records),
        "returned_count": len(snapshot.records),
        "has_more": snapshot.has_more,
        "content_sha256": snapshot.sha256,
        "coverage": snapshot.coverage,
    }


def verify_external(session, evidence, audit):
    expected_batches = set()
    checked = 0
    events = {(r["action"], r["subject_id"]) for r in audit}
    for row in evidence:
        if row["provider"] not in PROVIDERS:
            continue
        expected_batches.add(str(row["id"]))
        batch = (
            session.execute(text("SELECT * FROM source_batches WHERE id=:id"), {"id": row["id"]})
            .mappings()
            .one()
        )
        meta = batch["metadata"]
        if (
            row_hash(meta) != batch["metadata_sha256"]
            or ("EXTERNAL_SOURCE_BATCH_RECEIVED", f"{row['id']}:{batch['metadata_sha256']}") not in events
        ):
            raise ValueError("SOURCE_BATCH_AUDIT_MISMATCH")
        snap = parse_external(
            bytes(row["raw_bytes"]), row["source_request"], row["source_url"], meta["transport"]
        )
        if (
            DATASETS[snap.query["dataset"]].provider != row["provider"]
            or row["media_type"] != snap.media_type
            or snap.request_sha256 != row["request_sha256"]
            or meta["query"] != snap.query
            or meta["dataset"] != snap.query["dataset"]
            or meta["coverage"] != snap.coverage
            or batch["dataset"] != snap.query["dataset"]
        ):
            raise ValueError("SOURCE_BATCH_METADATA_MISMATCH")
        stored = (
            session.execute(
                text(
                    "SELECT source_key,body,source_locator,record_sha256,provenance_state FROM source_records WHERE evidence_id=:eid"
                ),
                {"eid": row["id"]},
            )
            .mappings()
            .all()
        )
        actual = {r["source_key"]: r for r in stored}
        if len(actual) != len(stored) or len(stored) != len(snap.records):
            raise ValueError("SOURCE_RECORD_COUNT_MISMATCH")
        for rec in snap.records:
            saved = actual.get(rec["key"])
            if (
                not saved
                or saved["body"] != rec["body"]
                or saved["source_locator"] != rec["locator"]
                or saved["record_sha256"] != row_hash(rec)
                or saved["provenance_state"] != "UNASSESSED"
            ):
                raise ValueError("SOURCE_RECORD_REPLAY_MISMATCH")
        checked += len(stored)
    batches = {str(i) for i in session.execute(text("SELECT id FROM source_batches")).scalars()}
    if batches != expected_batches:
        raise ValueError("SOURCE_BATCH_WITHOUT_ORIGINAL")
    return {"external_source_batches_checked": len(batches), "external_source_records_checked": checked}
