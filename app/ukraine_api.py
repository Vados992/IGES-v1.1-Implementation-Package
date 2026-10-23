"""Private professional-record search and explicit Ukrainian collection coverage."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.database import tenant_session
from app.external_api import READ

router = APIRouter(tags=["Ukraine public-source research"])


@router.get("/v1/sources/ukraine/search")
def search(
    q: str = Query(min_length=3, max_length=100),
    limit: int = Query(20, ge=1, le=100),
    cursor: UUID | None = None,
    user: dict = Depends(READ),
):
    escaped = q.strip().casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with tenant_session(read_only=True) as session:
        rows = (
            session.execute(
                text(
                    "SELECT r.id,r.evidence_id,b.dataset,r.source_key,r.body,r.source_locator,r.record_sha256,r.provenance_state "
                    "FROM source_records r JOIN source_batches b ON b.id=r.evidence_id "
                    "WHERE b.dataset IN ('ua_rada_roster','ua_rada_posts','ua_cec_elected_2020') "
                    "AND r.body->>'search_name' LIKE :q ESCAPE '\\' "
                    "AND (CAST(:cursor AS uuid) IS NULL OR r.id>CAST(:cursor AS uuid)) ORDER BY r.id LIMIT :limit"
                ),
                {"q": "%" + escaped + "%", "cursor": str(cursor) if cursor else None, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
        return jsonable_encoder(
            {
                "records": rows[:limit],
                "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
                "meaning": "Name search candidates only; rows/snapshots are not unique people or verified findings",
            }
        )


@router.get("/v1/sources/ukraine/coverage")
def coverage(user: dict = Depends(READ)):
    with tenant_session(read_only=True) as session:
        counts = (
            session.execute(
                text(
                    "SELECT b.dataset,e.source_request->'params'->>'term' AS convocation, "
                    "count(*) AS snapshot_records,count(DISTINCT r.source_key) AS distinct_source_keys, "
                    "count(DISTINCT b.id) AS batches,max(e.retrieved_at) AS last_received "
                    "FROM source_batches b JOIN source_records r ON r.evidence_id=b.id JOIN evidence e ON e.id=b.id "
                    "WHERE e.provider IN ('UA_RADA','UA_CEC') GROUP BY b.dataset,convocation ORDER BY b.dataset,convocation"
                )
            )
            .mappings()
            .all()
        )
        attempts = (
            session.execute(
                text(
                    "SELECT id,dataset,body,body_sha256,created_at FROM source_collection_attempts "
                    "ORDER BY created_at DESC LIMIT 100"
                )
            )
            .mappings()
            .all()
        )
        return jsonable_encoder(
            {
                "requested_years": [2014, 2026],
                "universe_complete": False,
                "record_counts": counts,
                "collection_attempts": attempts,
                "coverage_rules": [
                    "VII convocation covers the part of 2014 before VIII; records ending before 2014 excluded",
                    "VIII and IX are published membership records, not complete annual person snapshots",
                    "CEC records describe elections in the 2020 cycle, not current mandates",
                    "NAZK API documents reporting years from 2015; 2014 is not covered by that API",
                    "2026 is incomplete as of collection; no future records or inferred financial values",
                    "President, cabinet, regional appointments, local 2014-2019 mandates and later terminations require further authoritative ingestion",
                ],
                "publication": "Private research only; original personal data require counsel access; case/publication human gates remain mandatory",
            }
        )
