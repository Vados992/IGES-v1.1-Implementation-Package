"""Authenticated public-source research access; no automatic public redistribution."""

from dataclasses import asdict
import hashlib
import os
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.auth import require_role
from app.config import settings
from app.database import tenant_session
from app.external_catalog import DATASETS
from app.external_sources import canonical, fetch_external, validate_query, parse_external
from app.external_persistence import store_external
from app.persistence import append_audit
from app.workflow import Writer, insert, one

router = APIRouter(tags=["Public-source research"])
READ = require_role("ingestor", "analyst", "editor", "reviewer", "counsel", "panel", "reader")


class Ingest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: str = Field(max_length=80)
    params: dict[str, str] = Field(default_factory=dict, max_length=10)
    page: int = Field(default=1, ge=1, le=100)
    limit: int = Field(default=100, ge=1, le=1000)


class Admission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: UUID


@router.get("/v1/sources/catalog")
def catalog(user: dict = Depends(READ)):
    records = []
    for key, spec in DATASETS.items():
        item = {"dataset": key, **asdict(spec)}
        item["max_page_size"] = 200 if spec.provider in {"CFTC", "GLEIF"} else 1000
        item["configured"] = spec.provider != "ALPACA" or bool(
            os.getenv("IGES_ALPACA_DATA_KEY") and os.getenv("IGES_ALPACA_DATA_SECRET")
        )
        item["meaning"] = "Source-attributed, UNASSESSED; not customer account records or verified findings"
        records.append(item)
    return {
        "records": records,
        "direct_http_only": True,
        "existing_adapters": ["WORLD_BANK", "USA_SPENDING"],
        "access": "Authenticated research only; publication requires case gates",
    }


def prior_receipt(session, actor, key, sha):
    prior = (
        session.execute(
            text(
                "SELECT response,request_hash FROM write_receipts WHERE actor=:actor AND key=:key AND request_path='POST /v1/sources/ingest'"
            ),
            {"actor": actor, "key": key},
        )
        .mappings()
        .first()
    )
    if prior:
        if prior["request_hash"] != sha:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
        return prior["response"]
    return None


@router.post("/v1/sources/ingest", status_code=201)
async def ingest(
    body: Ingest,
    user: dict = Depends(require_role("ingestor")),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
):
    try:
        query = validate_query(body.dataset, body.params, body.page, body.limit)
    except ValueError:
        raise HTTPException(422, "INVALID_SOURCE_QUERY") from None
    sha = hashlib.sha256(canonical(query).encode()).hexdigest()

    def check():
        with tenant_session(read_only=True) as session:
            return prior_receipt(session, user["sub"], key, sha)

    prior = await run_in_threadpool(check)
    if prior is not None:
        return prior
    try:
        snapshot = await fetch_external(body.dataset, body.params, body.page, body.limit)
    except Exception as error:
        # No provider body, token, private query or network exception details are exposed.
        if isinstance(error, ValueError) and str(error) == "ALPACA_MARKET_DATA_CREDENTIALS_REQUIRED":
            raise HTTPException(503, "MARKET_DATA_CREDENTIALS_REQUIRED") from None
        raise HTTPException(503, "OFFICIAL_SOURCE_UNAVAILABLE_OR_INVALID") from None

    def save():
        with tenant_session() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"source-write:{user['sub']}:{key}"},
            )
            prior = prior_receipt(session, user["sub"], key, sha)
            if prior is not None:
                return prior
            result = store_external(session, snapshot, user["sub"])
            session.execute(
                text(
                    "INSERT INTO write_receipts(project_id,actor,request_path,key,request_hash,response) VALUES(:pid,:actor,'POST /v1/sources/ingest',:key,:sha,CAST(:result AS jsonb))"
                ),
                {
                    "pid": str(settings.project_id),
                    "actor": user["sub"],
                    "key": key,
                    "sha": sha,
                    "result": canonical(result),
                },
            )
            return result

    return await run_in_threadpool(save)


@router.get("/v1/sources/batches")
def batches(
    dataset: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: UUID | None = None,
    user: dict = Depends(READ),
):
    if dataset is not None and dataset not in DATASETS:
        raise HTTPException(422, "UNKNOWN_DATASET")
    with tenant_session(read_only=True) as session:
        records = (
            session.execute(
                text(
                    "SELECT b.id,b.dataset,b.metadata,e.content_sha256,e.retrieved_at "
                    "FROM source_batches b JOIN evidence e ON e.id=b.id "
                    "WHERE (CAST(:dataset AS text) IS NULL OR b.dataset=:dataset) AND (CAST(:cursor AS uuid) IS NULL OR b.id>CAST(:cursor AS uuid)) ORDER BY b.id LIMIT :limit"
                ),
                {"dataset": dataset, "cursor": str(cursor) if cursor else None, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
        return jsonable_encoder(
            {
                "records": records[:limit],
                "next_cursor": str(records[limit - 1]["id"]) if len(records) > limit else None,
            }
        )


@router.get("/v1/sources/batches/{bid}/records")
def records(
    bid: UUID, limit: int = Query(50, ge=1, le=100), cursor: UUID | None = None, user: dict = Depends(READ)
):
    with tenant_session(read_only=True) as session:
        one(session, "SELECT id FROM source_batches WHERE id=:id", id=str(bid))
        found = (
            session.execute(
                text(
                    "SELECT id,source_key,body,source_locator,record_sha256,provenance_state FROM source_records WHERE evidence_id=:eid "
                    "AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT :limit"
                ),
                {"eid": str(bid), "cursor": str(cursor) if cursor else None, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
        return jsonable_encoder(
            {
                "records": found[:limit],
                "next_cursor": str(found[limit - 1]["id"]) if len(found) > limit else None,
            }
        )


@router.get("/v1/sources/batches/{bid}/original")
def original(
    bid: UUID, user: dict = Depends(require_role("ingestor", "analyst", "editor", "reviewer", "counsel"))
):
    with tenant_session() as session:
        row = one(
            session,
            "SELECT e.*,b.metadata FROM evidence e JOIN source_batches b ON b.id=e.id WHERE e.id=:id",
            id=str(bid),
        )
        snap = parse_external(
            bytes(row["raw_bytes"]), row["source_request"], row["source_url"], row["metadata"]["transport"]
        )
        if snap.sha256 != row["content_sha256"] or snap.request_sha256 != row["request_sha256"]:
            raise HTTPException(409, "SOURCE_HASH_MISMATCH")
        append_audit(session, user["sub"], "SOURCE_ORIGINAL_ACCESSED", str(bid))
        return Response(
            snap.raw,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{bid}.source"',
                "X-Content-SHA256": snap.sha256,
            },
        )


@router.post("/v1/cases/{cid}/source-admissions", status_code=201)
def admit(cid: UUID, body: Admission, writer: Writer = Depends()):
    def copy(session, rev):
        row = one(
            session,
            "SELECT e.*,b.dataset,b.metadata FROM evidence e JOIN source_batches b ON b.id=e.id WHERE e.id=:id",
            id=str(body.evidence_id),
        )
        snap = parse_external(
            bytes(row["raw_bytes"]), row["source_request"], row["source_url"], row["metadata"]["transport"]
        )
        if snap.sha256 != row["content_sha256"] or snap.request_sha256 != row["request_sha256"]:
            raise HTTPException(409, "SOURCE_HASH_MISMATCH")
        spec = DATASETS[row["dataset"]]
        source = {
            "title": spec.title,
            "publisher": spec.provider,
            "author": None,
            "published_at": None,
            "language": "en",
            "url": snap.url if len(snap.url) <= 2000 else spec.documentation,
            "primacy": "derivative" if snap.transport == "MCP_TOOL" else "primary",
            "independence_group": spec.provider,
            "provenance_basis": f"Preserved batch {row['id']}, request {snap.request_sha256}, original SHA-256 {snap.sha256}; transport {snap.transport}; {spec.limitations}",
        }
        sid = insert(session, "sources", cid, writer.user, source)
        did = insert(
            session,
            "documents",
            cid,
            writer.user,
            None,
            source_id=str(sid),
            sha256=snap.sha256,
            raw_bytes=snap.raw,
            mime="application/octet-stream",
            size_bytes=len(snap.raw),
            doc_version=1,
        )
        return {
            "id": did,
            "source_id": sid,
            "evidence_id": str(body.evidence_id),
            "status": "PENDING",
            "sha256": snap.sha256,
        }

    return writer.run(
        cid, ["analyst", "editor"], body.model_dump(mode="json"), "EXTERNAL_SOURCE_ADMITTED", copy
    )
