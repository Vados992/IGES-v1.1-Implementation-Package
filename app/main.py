"""Read-only public research API and OIDC-protected controlled-pilot writes."""
from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.auth import require_role, https_endpoint, verified_identity
from app.config import settings
from app.database import tenant_session, check_database
from app.middleware import BodyLimitMiddleware, RateLimitMiddleware
from app.persistence import append_audit, store_snapshot, store_awards
from app.usaspending import fetch_awards, MAX_FISCAL_YEAR
from app.worldbank import ALLOWED_INDICATORS, fetch_snapshot
from app.workflow import router as workflow_router
from app.problems import install as install_problems
from app.external_api import router as external_router
from app.ukraine_api import router as ukraine_router

app = FastAPI(
    title="IGES v1.1 Controlled Pilot",
    version="1.1.0-pilot",
    description="Source-attributed public economic records; no automated political verdicts.",
)
app.add_middleware(BodyLimitMiddleware, max_bytes=65536)
app.add_middleware(RateLimitMiddleware)
app.include_router(workflow_router)
app.include_router(external_router)
app.include_router(ukraine_router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html", headers={
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'"})


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


@app.get('/workspace', include_in_schema=False)
def workspace():
    return FileResponse(STATIC_DIR / 'workspace.html', headers={
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})


@app.get('/publication', include_in_schema=False)
def publication_reader():
    return FileResponse(STATIC_DIR / 'publication.html', headers={
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})


class IngestRequest(RequestModel):
    country: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    indicator: str
    start: int = Field(ge=1960, le=2100)
    end: int = Field(ge=1960, le=2100)


class AwardIngestRequest(RequestModel):
    fiscal_year: int = Field(ge=2008, le=MAX_FISCAL_YEAR)
    limit: int = Field(default=10, ge=1, le=25)


class AttestationRequest(RequestModel):
    method: str = Field(pattern=r"^(OFFICIAL_API|DIGITAL_SIGNATURE|INDEPENDENT_CORROBORATION)$")
    rationale: str = Field(min_length=20, max_length=5000)
    proof_url: str | None = Field(default=None, max_length=2000)


class FinanceEventRequest(RequestModel):
    evidence_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=128)
    stage: str = Field(
        pattern=r"^(COMMITMENT|APPROPRIATION|OBLIGATION|CONTRACT|DISBURSEMENT|RECEIPT|EXPENDITURE|REFUND|REVERSAL)$"
    )
    amount: str = Field(pattern=r"^[0-9]{1,24}(\.[0-9]{1,8})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    external_reference: str = Field(min_length=1, max_length=500)
    payer_name: str | None = Field(default=None, max_length=500)
    payee_name: str | None = Field(default=None, max_length=500)
    related_event_id: UUID | None = None


class ClaimRequest(RequestModel):
    statement: str = Field(min_length=10, max_length=5000)
    evidence_id: UUID


class ReviewRequest(RequestModel):
    verdict: str = Field(pattern=r"^(SUPPORT|CONTRADICT|INSUFFICIENT)$")
    rationale: str = Field(min_length=20, max_length=5000)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "DATABASE_UNAVAILABLE"})


install_problems(app)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz")
def health():
    return {"status": "alive", "environment": "controlled_pilot"}


@app.get("/v1/admin/whoami")
def whoami(user: dict = Depends(verified_identity)):
    return {"subject": user["sub"], "project_id": user["project_id"],
            "roles": user.get("roles", []), "amr": user.get("amr", []),
            "acr": user.get("acr"), "auth_time": user.get("auth_time"),
            "mfa_enforced": settings.oidc_require_mfa}


@app.get('/v1/auth/config')
def browser_auth_config():
    if not all((settings.oidc_issuer, settings.oidc_jwks_url, settings.oidc_audience)) or not https_endpoint(settings.oidc_issuer):
        raise HTTPException(503, 'OIDC_NOT_CONFIGURED')
    return {'issuer': settings.oidc_issuer, 'client_id': os.getenv('IGES_OIDC_WEB_CLIENT_ID', 'iges-web'),
            'audience': settings.oidc_audience, 'flow': 'authorization_code_pkce', 'mfa_required': settings.oidc_require_mfa}


@app.get("/readyz")
def ready():
    try:
        with tenant_session(read_only=True) as session:
            check_database(session)
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="DATABASE_UNAVAILABLE") from None


@app.get("/v1/public/observations")
def public_observations(
    country: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    indicator: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    if indicator is not None and indicator not in ALLOWED_INDICATORS:
        raise HTTPException(status_code=422, detail="INDICATOR_NOT_ALLOWED")
    query = text("""
        SELECT id::text AS id, country_code, indicator_code, period,
               numeric_value::text AS value, observation_status,
               provider, source_url, retrieved_at, content_sha256,
               source_locator, provenance_state
        FROM (
          SELECT DISTINCT ON (o.country_code, o.indicator_code, o.period)
                 o.id, o.country_code, o.indicator_code, o.period,
                 o.numeric_value, o.observation_status, o.source_locator,
                 e.provider, e.source_url, e.retrieved_at, e.content_sha256,
                 e.provenance_state
          FROM observations o
          JOIN evidence e ON e.id=o.evidence_id AND e.project_id=o.project_id
          WHERE (CAST(:country AS text) IS NULL OR o.country_code=:country)
            AND (CAST(:indicator AS text) IS NULL OR o.indicator_code=:indicator)
          ORDER BY o.country_code, o.indicator_code, o.period,
                   e.retrieved_at DESC, o.id DESC
        ) latest
        ORDER BY period DESC, country_code, indicator_code LIMIT :limit
    """)
    with tenant_session(read_only=True) as session:
        rows = session.execute(
            query, {"country": country, "indicator": indicator, "limit": limit}
        ).mappings().all()
        return {"records": [dict(row) for row in rows], "count": len(rows),
                "meaning": "Source-attributed observations, not independently verified conclusions"}


@app.get("/v1/public/observations/{observation_id}/provenance")
def observation_provenance(observation_id: UUID):
    with tenant_session(read_only=True) as session:
        row = session.execute(
            text("""
            SELECT o.id::text AS observation_id, o.source_locator, o.period,
                   e.id::text AS evidence_id, e.provider, e.source_url,
                   e.retrieved_at, e.content_sha256, e.provenance_state, e.media_type
            FROM observations o
            JOIN evidence e ON e.id=o.evidence_id AND e.project_id=o.project_id
            WHERE o.id=:oid
            """),
            {"oid": str(observation_id)},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="OBSERVATION_NOT_FOUND")
        return dict(row)


@app.post("/v1/admin/ingest/worldbank")
async def ingest_worldbank(
    body: IngestRequest, user: dict = Depends(require_role("ingestor"))
):
    if body.end < body.start or body.end - body.start > 30:
        raise HTTPException(status_code=422, detail="INVALID_YEAR_RANGE")
    if body.indicator not in ALLOWED_INDICATORS:
        raise HTTPException(status_code=422, detail="INDICATOR_NOT_ALLOWED")
    try:
        snapshot = await fetch_snapshot(body.country, body.indicator, body.start, body.end)
    except (httpx.HTTPError, ValueError, UnicodeDecodeError, TimeoutError, RecursionError):
        raise HTTPException(status_code=502, detail="UPSTREAM_INVALID_OR_UNAVAILABLE") from None
    def persist():
        with tenant_session() as session:
            return store_snapshot(session, snapshot, user["sub"])
    evidence_id, count, created = await run_in_threadpool(persist)
    return {"evidence_id": evidence_id, "inserted_observations": count,
            "new_snapshot": created, "content_sha256": snapshot.sha256,
            "provenance_state": "UNASSESSED"}


@app.get("/v1/public/awards")
def public_awards(limit: int = Query(default=50, ge=1, le=100)):
    with tenant_session(read_only=True) as session:
        rows = session.execute(text("""
            SELECT id::text AS id,source_award_key,external_award_id,recipient_name,
                   awarding_agency,funding_agency,award_amount::text AS award_amount,currency,
                   source_locator,source_url,source_request,retrieved_at,content_sha256,
                   request_sha256,provenance_state
            FROM (
              SELECT DISTINCT ON (a.source_award_key)
                a.*,e.source_url,e.source_request,e.retrieved_at,e.content_sha256,
                e.request_sha256,e.provenance_state
              FROM public_awards a JOIN evidence e ON e.id=a.evidence_id AND e.project_id=a.project_id
              ORDER BY a.source_award_key,e.retrieved_at DESC,a.id DESC
            ) recent ORDER BY recent.award_amount DESC NULLS LAST,source_award_key LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return {"count": len(rows), "records": [dict(row) for row in rows],
            "meaning": "USAspending award amount, not a verified disbursement or expenditure",
            "coverage": "Only ingested search pages; not all federal awards"}


@app.get("/v1/public/awards/{award_id}/provenance")
def award_provenance(award_id: UUID):
    with tenant_session(read_only=True) as session:
        row = session.execute(text("""
            SELECT a.id::text AS award_record_id,a.source_locator,e.id::text AS evidence_id,
                   e.provider,e.source_url,e.source_request,e.retrieved_at,e.content_sha256,
                   e.request_sha256,e.provenance_state
            FROM public_awards a JOIN evidence e ON e.id=a.evidence_id AND e.project_id=a.project_id
            WHERE a.id=:id
        """), {"id": str(award_id)}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="AWARD_NOT_FOUND")
    return dict(row)


@app.post("/v1/admin/ingest/usaspending")
async def ingest_usaspending(body: AwardIngestRequest, user: dict = Depends(require_role("ingestor"))):
    try:
        snapshot = await fetch_awards(body.fiscal_year, body.limit)
    except (httpx.HTTPError, ValueError, UnicodeDecodeError, TimeoutError, RecursionError):
        raise HTTPException(status_code=502, detail="UPSTREAM_INVALID_OR_UNAVAILABLE") from None

    def persist():
        with tenant_session() as session:
            return store_awards(session, snapshot, user["sub"])

    evidence_id, count, created = await run_in_threadpool(persist)
    return {"evidence_id": evidence_id, "awards_inserted": count, "new_snapshot": created,
            "content_sha256": snapshot.sha256, "request_sha256": snapshot.request_sha256,
            "has_next_page": snapshot.has_next_page, "provenance_state": "UNASSESSED"}


@app.post("/v1/admin/evidence/{evidence_id}/attest")
def attest_evidence(
    evidence_id: UUID, body: AttestationRequest,
    user: dict = Depends(require_role("reviewer"))
):
    if body.proof_url is not None and not https_endpoint(body.proof_url):
        raise HTTPException(status_code=422, detail="PROOF_URL_HTTPS_REQUIRED")
    with tenant_session() as session:
        found = session.execute(
            text("SELECT 1 FROM evidence WHERE id=:eid"),
            {"eid": str(evidence_id)},
        ).first()
        if found is None:
            raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
        try:
            # Savepoint allows a duplicate to be reported without aborting outer audit transaction.
            with session.begin_nested():
                aid = session.execute(
                    text("INSERT INTO evidence_attestations "
                         "(project_id,evidence_id,attester_sub,method,rationale,proof_url) "
                         "VALUES (current_setting('iges.project_id')::uuid,:eid,:actor,:method,:rationale,:url) "
                         "RETURNING id"),
                    {"eid": str(evidence_id), "actor": user["sub"],
                     "method": body.method, "rationale": body.rationale,
                     "url": body.proof_url},
                ).scalar_one()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="DUPLICATE_ATTESTATION") from None
        append_audit(session, user["sub"], "EVIDENCE_ATTESTED", str(evidence_id))
        return {"attestation_id": str(aid), "meaning": "Origin attestation is not proof of claim truth"}


@app.post("/v1/admin/financial/events")
def add_financial_event(
    body: FinanceEventRequest, user: dict = Depends(require_role("analyst"))
):
    amount = Decimal(body.amount)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="AMOUNT_MUST_BE_POSITIVE")
    with tenant_session() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": "iges-finance:" + str(settings.project_id)})
        prior = session.execute(
            text("SELECT * FROM financial_events WHERE idempotency_key=:key"),
            {"key": body.idempotency_key},
        ).mappings().first()
        if prior is not None:
            unchanged = (
                str(prior["evidence_id"]) == str(body.evidence_id)
                and prior["stage"] == body.stage
                and prior["original_amount"] == amount
                and prior["currency"] == body.currency
                and prior["external_reference"] == body.external_reference
                and prior["payer_name"] == body.payer_name
                and prior["payee_name"] == body.payee_name
                and (str(prior["related_event_id"]) if prior["related_event_id"] else None)
                    == (str(body.related_event_id) if body.related_event_id else None)
            )
            if not unchanged:
                raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
            return {"event_id": str(prior["id"]), "created": False}
        if body.stage in {"REFUND", "REVERSAL"}:
            if body.related_event_id is None:
                raise HTTPException(status_code=422, detail="RETURN_REQUIRES_LINKED_DISBURSEMENT")
            origin = session.execute(
                text("SELECT stage,currency,original_amount FROM financial_events WHERE id=:eid"),
                {"eid": str(body.related_event_id)},
            ).mappings().first()
            if origin is None or origin["stage"] != "DISBURSEMENT" or origin["currency"] != body.currency:
                raise HTTPException(status_code=422, detail="INVALID_RETURN_REFERENCE")
            consumed = session.execute(
                text("SELECT COALESCE(SUM(original_amount),0) FROM financial_events "
                     "WHERE related_event_id=:eid AND stage IN ('REFUND','REVERSAL')"),
                {"eid": str(body.related_event_id)},
            ).scalar_one()
            if consumed + amount > origin["original_amount"]:
                raise HTTPException(status_code=409, detail="RETURN_EXCEEDS_DISBURSEMENT")
        elif body.related_event_id is not None:
            raise HTTPException(status_code=422, detail="UNEXPECTED_RELATED_EVENT")
        try:
            with session.begin_nested():
                event_id = session.execute(
                    text("INSERT INTO financial_events "
                         "(project_id,evidence_id,idempotency_key,stage,original_amount,currency,"
                         "external_reference,payer_name,payee_name,related_event_id) "
                         "VALUES (current_setting('iges.project_id')::uuid,:evidence,:key,:stage,"
                         ":amount,:currency,:reference,:payer,:payee,:linked) RETURNING id"),
                    {"evidence": str(body.evidence_id), "key": body.idempotency_key,
                     "stage": body.stage, "amount": amount,
                     "currency": body.currency, "reference": body.external_reference,
                     "payer": body.payer_name, "payee": body.payee_name,
                     "linked": str(body.related_event_id) if body.related_event_id else None},
                ).scalar_one()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="EVENT_DUPLICATE_OR_EVIDENCE_MISSING") from None
        append_audit(session, user["sub"], "FINANCIAL_EVENT_RECORDED", str(event_id))
        return {"event_id": str(event_id), "created": True,
                "note": "Recorded as sourced event; not automatically treated as a verified transfer"}


@app.post("/v1/admin/claims", deprecated=True)
def create_claim(body: ClaimRequest, user: dict = Depends(require_role("analyst"))):
    raise HTTPException(410, 'USE_CASE_SCOPED_CLAIMS_WITH_PERIOD_AND_JURISDICTION')


@app.post("/v1/admin/claims/{claim_id}/reviews")
def review_claim(
    claim_id: UUID, body: ReviewRequest, user: dict = Depends(require_role("reviewer"))
):
    with tenant_session() as session:
        claim = session.execute(
            text("SELECT submitted_by,evidence_id FROM claims WHERE id=:id"),
            {"id": str(claim_id)},
        ).mappings().first()
        if claim is None:
            raise HTTPException(status_code=404, detail="CLAIM_NOT_FOUND")
        if claim["submitted_by"] == user["sub"]:
            raise HTTPException(status_code=403, detail="SELF_REVIEW_FORBIDDEN")
        if body.verdict == "SUPPORT":
            is_attested = session.execute(
                text("SELECT 1 FROM evidence_attestations WHERE evidence_id=:eid "
                     "AND attester_sub <> :author LIMIT 1"),
                {"eid": str(claim["evidence_id"]), "author": claim["submitted_by"]},
            ).first()
            if not is_attested:
                raise HTTPException(status_code=409, detail="ORIGIN_ATTESTATION_REQUIRED")
        try:
            with session.begin_nested():
                review_id = session.execute(
                    text("INSERT INTO reviews "
                         "(project_id,claim_id,reviewer_sub,verdict,rationale) "
                         "VALUES (current_setting('iges.project_id')::uuid,:cid,:sub,:verdict,:rationale) "
                         "RETURNING id"),
                    {"cid": str(claim_id), "sub": user["sub"],
                     "verdict": body.verdict, "rationale": body.rationale},
                ).scalar_one()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="REVIEWER_ALREADY_REVIEWED") from None
        append_audit(session, user["sub"], "CLAIM_REVIEWED", str(claim_id))
        return {"review_id": str(review_id), "published": False,
                "meaning": "One independent assessment; no automatic status escalation or publication"}
