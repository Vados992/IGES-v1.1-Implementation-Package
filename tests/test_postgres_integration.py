"""Executed against a disposable Compose database, never a working operator database."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.auth import verified_identity
from app.config import settings
from app.database import tenant_session, _factory
from app.main import app
from app.persistence import append_audit, store_snapshot
from app.verify_integrity import verify_integrity
from app.worldbank import parse_snapshot

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.getenv("IGES_TEST_ADMIN_URL"), reason="disposable PostgreSQL required")]


@pytest.fixture(scope="module")
def admin():
    engine = create_engine(os.environ["IGES_TEST_ADMIN_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[verified_identity] = lambda: {
        "sub": "integration-author", "roles": ["analyst", "ingestor", "reviewer"]}
    with TestClient(app) as instance:
        yield instance
    app.dependency_overrides.clear()


def snapshot(value=None):
    raw = json.dumps([{"page": 1, "pages": 1, "total": 1, "test_snapshot": str(uuid4())},
                      [{"countryiso3code": "PRT", "indicator": {"id": "SP.POP.TOTL"},
                        "date": "2024", "value": value, "obs_status": ""}]]).encode()
    return parse_snapshot(raw, "https://api.worldbank.org/v2/country/PRT/indicator/SP.POP.TOTL?format=json&date=2024:2024&per_page=100",
                          "PRT", "SP.POP.TOTL", 2024, 2024)


@pytest.fixture
def evidence():
    with tenant_session() as session:
        eid, _, _ = store_snapshot(session, snapshot(), "INTEGRATION_FIXTURE")
    return eid


def test_real_readiness_and_unfiltered_public_query(client):
    assert client.get("/readyz").status_code == 200
    response = client.get("/v1/public/observations")
    assert response.status_code == 200
    assert response.json()["count"] >= 0


def test_import_null_precision_and_idempotence(client):
    snap = snapshot()
    with tenant_session() as session:
        first = store_snapshot(session, snap, "INTEGRATION_FIXTURE")
    with tenant_session() as session:
        second = store_snapshot(session, snap, "INTEGRATION_FIXTURE")
    assert first[1:] == (1, True)
    assert second == (first[0], 0, False)
    with tenant_session(read_only=True) as session:
        assert session.execute(text("SELECT numeric_value FROM observations WHERE evidence_id=:eid"),
                               {"eid": first[0]}).scalar_one() is None
    response = client.get("/v1/public/observations?country=PRT&indicator=SP.POP.TOTL")
    assert response.status_code == 200
    record = response.json()["records"][0]
    provenance = client.get(f"/v1/public/observations/{record['id']}/provenance")
    assert provenance.status_code == 200
    assert "raw_bytes" not in provenance.json()


def test_rls_context_cannot_switch_login_project(admin):
    other = str(uuid4())
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO projects(id,name) VALUES (:id,'other test project')"), {"id": other})
    with _factory()() as session, session.begin():
        assert session.execute(text("SELECT count(*) FROM projects")).scalar_one() == 0
        session.execute(text("SELECT set_config('iges.project_id',:pid,true)"), {"pid": other})
        assert session.execute(text("SELECT count(*) FROM projects")).scalar_one() == 0
        with pytest.raises(DBAPIError):
            session.execute(text("INSERT INTO claims(project_id,evidence_id,statement,submitted_by) "
                                 "VALUES (:pid,:eid,'Cross project claim','actor')"),
                            {"pid": other, "eid": str(uuid4())})


@pytest.mark.parametrize("statement", ["UPDATE evidence SET provider=provider", "DELETE FROM evidence",
                                       "TRUNCATE evidence CASCADE", "SELECT * FROM runtime_projects"])
def test_runtime_cannot_mutate_history_or_binding(statement):
    with pytest.raises(DBAPIError), tenant_session() as session:
        session.execute(text(statement))


def test_readonly_transaction_cannot_write(evidence):
    with pytest.raises(DBAPIError), tenant_session(read_only=True) as session:
        append_audit(session, "test", "READ_ONLY_MUST_FAIL", evidence)


def test_concurrent_import_is_one_snapshot():
    snap = snapshot()

    def write(_):
        with tenant_session() as session:
            return store_snapshot(session, snap, "INTEGRATION_FIXTURE")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(4)))
    assert sum(row[2] for row in results) == 1
    assert len({row[0] for row in results}) == 1


def finance_body(evidence, **changes):
    body = {"evidence_id": evidence, "idempotency_key": str(uuid4()), "stage": "DISBURSEMENT",
            "amount": "100.00", "currency": "EUR", "external_reference": "TEST FIXTURE, NOT REAL MONEY"}
    body.update(changes)
    return body


def test_concurrent_financial_idempotency_and_conflict(client, evidence):
    body = finance_body(evidence)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/v1/admin/financial/events", json=body), range(4)))
    assert [r.status_code for r in responses] == [200] * 4
    assert sum(r.json()["created"] for r in responses) == 1
    assert len({r.json()["event_id"] for r in responses}) == 1
    body["amount"] = "101"
    assert client.post("/v1/admin/financial/events", json=body).status_code == 409


def test_concurrent_returns_cannot_exceed_disbursement(client, evidence):
    origin = client.post("/v1/admin/financial/events", json=finance_body(evidence)).json()["event_id"]
    bodies = [finance_body(evidence, stage=stage, amount="60", related_event_id=origin)
              for stage in ["REFUND", "REVERSAL"]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda body: client.post("/v1/admin/financial/events", json=body), bodies))
    assert sorted(r.status_code for r in responses) == [200, 409]


def test_direct_sql_cannot_bypass_financial_return_limit(client, evidence):
    origin = client.post("/v1/admin/financial/events", json=finance_body(evidence)).json()["event_id"]

    def write(_):
        try:
            with tenant_session() as session:
                session.execute(text("INSERT INTO financial_events "
                                     "(project_id,evidence_id,idempotency_key,stage,original_amount,currency,external_reference,related_event_id) "
                                     "VALUES (:pid,:eid,:key,'REFUND',60,'EUR','TEST FIXTURE',:origin)"),
                                {"pid": str(settings.project_id), "eid": evidence,
                                 "key": str(uuid4()), "origin": origin})
            return True
        except DBAPIError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, range(2))) == [False, True]


def test_two_person_review_enforced_in_api_and_database(client, evidence):
    assert client.post('/v1/admin/claims', json={'evidence_id': evidence,
                                              'statement': 'Controlled integration test claim'}).status_code == 410
    # Preserve verification of historical review constraints without creating new unscoped claims via the API.
    with tenant_session() as session:
        claim = str(session.execute(text("INSERT INTO claims(project_id,evidence_id,statement,submitted_by) "
                           "VALUES(:pid,:eid,'EXPLICIT LEGACY TEST FIXTURE','integration-author') RETURNING id"),
                       {'pid': str(settings.project_id), 'eid': evidence}).scalar_one())
        append_audit(session, 'INTEGRATION_FIXTURE', 'LEGACY_TEST_CLAIM', claim)
    review = {"verdict": "SUPPORT", "rationale": "Integration fixture rationale with sufficient length"}
    assert client.post(f"/v1/admin/claims/{claim}/reviews", json=review).status_code == 403
    with pytest.raises(DBAPIError), tenant_session() as session:
        session.execute(text("INSERT INTO reviews(project_id,claim_id,reviewer_sub,verdict,rationale) "
                             "VALUES (:pid,:cid,'integration-author','INSUFFICIENT',:why)"),
                        {"pid": str(settings.project_id), "cid": claim, "why": review["rationale"]})
    app.dependency_overrides[verified_identity] = lambda: {"sub": "integration-reviewer", "roles": ["reviewer"]}
    try:
        assert client.post(f"/v1/admin/claims/{claim}/reviews", json=review).status_code == 409
        attestation = {"method": "OFFICIAL_API", "rationale": review["rationale"]}
        assert client.post(f"/v1/admin/evidence/{evidence}/attest", json=attestation).status_code == 200
        assert client.post(f"/v1/admin/claims/{claim}/reviews", json=review).status_code == 200
        assert client.post(f"/v1/admin/claims/{claim}/reviews", json=review).status_code == 409
    finally:
        app.dependency_overrides[verified_identity] = lambda: {
            "sub": "integration-author", "roles": ["analyst", "ingestor", "reviewer"]}


def test_concurrent_audit_and_verification():
    def write(index):
        with tenant_session() as session:
            append_audit(session, "INTEGRATION_FIXTURE", "CONCURRENT_TEST", str(index))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))
    result = verify_integrity()
    assert result["audit_entries_checked"] >= 12
    assert result["externally_anchored"] is False
