"""EXPLICIT control fixtures only; actual source receipts are checked separately in live CI."""

import asyncio
import hashlib
import json
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, text

from app.auth import verified_identity
from app.config import settings
from app.database import tenant_session
from app.external_catalog import DATASETS
from app.external_persistence import store_external
from app.external_sources import canonical, fetch_external, parse_external, request_for, validate_query
from app.main import app
from app.verify_integrity import verify_integrity


def fixture_raw(marker="EXPLICIT_TEST_FIXTURE"):
    return json.dumps(
        {
            "meta": {
                "total": 1,
                "parameters": {"limit": "1", "offset": "0", "filters": "ACTIVE:1"},
                "index": {"name": "EXPLICIT_TEST_FIXTURE_INDEX"},
            },
            "data": [
                {
                    "data": {
                        "ID": "14",
                        "CERT": 14,
                        "NAME": "EXPLICIT_TEST_FIXTURE",
                        "ACTIVE": 1,
                        "ASSET": None,
                        "DEP": 12.125,
                    }
                }
            ],
            "fixture_marker": marker,
        }
    ).encode()


def snapshot(raw=None):
    query = validate_query("fdic_institutions", {}, limit=1)
    endpoint, args = request_for(query)
    return parse_external(raw or fixture_raw(), query, str(httpx.URL(endpoint, params=args)))


@pytest.mark.parametrize("dataset", sorted(DATASETS))
def test_catalog_requests_are_fixed_https_and_do_not_accept_urls(dataset):
    q = validate_query(dataset, {})
    endpoint, args = request_for(q)
    assert endpoint.startswith("https://")
    assert not any(k.lower() in {"authorization", "token", "secret", "password"} for k in args)
    with pytest.raises(ValueError):
        validate_query(dataset, {"url": "http://127.0.0.1/private"})


@pytest.mark.parametrize(
    "query",
    [
        ("hmlr_ppd", {"postcode": 'X". SERVICE <http://localhost> {} #'}),
        ("gleif_lei", {"name": "Bank' OR 1=1"}),
        ("nyc_acris", {"start": "2024-01-01' OR true"}),
        ("ecb_fx", {"currency": "USD/../../private"}),
        ("fdic_institutions", {"state": "XX OR ACTIVE:0"}),
        ("fdic_financials", {"report_date": "2024-12-30"}),
        ("alpaca_stock_bars", {"symbols": "JPM,JPM"}),
    ],
)
def test_source_query_injection_and_ambiguous_scope_denied(query):
    with pytest.raises(ValueError):
        validate_query(*query)


def test_exact_numbers_nulls_duplicates_and_request_binding():
    snap = snapshot()
    body = snap.records[0]["body"]
    assert body["source_fields"]["ASSET"] is None
    assert body["source_fields"]["DEP"] == "12.125"
    assert body["numeric_units"]["DEP"] == "USD_thousands"
    assert snap.sha256 == hashlib.sha256(fixture_raw()).hexdigest()
    invalid = json.loads(fixture_raw())
    invalid["data"] *= 2
    with pytest.raises(ValueError):
        snapshot(json.dumps(invalid).encode())
    invalid = json.loads(fixture_raw())
    invalid["meta"]["parameters"]["offset"] = "5"
    with pytest.raises(ValueError):
        snapshot(json.dumps(invalid).encode())
    with pytest.raises(ValueError):
        parse_external(snap.raw, snap.query, "https://untrusted.invalid")
    with pytest.raises(ValueError):
        snapshot(b'{"meta":{},"meta":{}}')


def test_jsonstat_missing_is_null_and_dimension_order_preserved():
    query = validate_query("eurostat_hpi", {"country": "PT", "start": "2024-01-01", "end": "2024-06-30"})
    endpoint, args = request_for(query)
    raw = json.dumps(
        {
            "class": "dataset",
            "version": "2.0",
            "source": "ESTAT",
            "id": ["time", "geo", "unit", "purchase", "freq"],
            "size": [2, 1, 1, 1, 1],
            "dimension": {
                k: {"category": {"index": v}}
                for k, v in {
                    "time": {"2024-Q1": 0, "2024-Q2": 1},
                    "geo": {"PT": 0},
                    "unit": {"I15_Q": 0},
                    "purchase": {"TOTAL": 0},
                    "freq": {"Q": 0},
                }.items()
            },
            "value": {"0": 123.125},
            "status": {"1": "u"},
        }
    ).encode()
    result = parse_external(raw, query, str(httpx.URL(endpoint, params=args)))
    assert [r["body"]["value"] for r in result.records] == ["123.125", None]
    assert result.records[1]["body"]["status"] == "u"
    assert result.records[1]["key"] == "PT:2024-Q2"


def test_acris_document_id_is_not_a_unique_row_and_old_receipts_replay():
    query = validate_query("nyc_acris", {"start": "2024-01-01", "end": "2024-01-31"}, limit=2)
    base = {
        "document_id": "EXPLICIT_TEST_DOCUMENT",
        "recorded_datetime": "2024-01-02T00:00:00.000",
        "document_amt": "0",
        "doc_type": "DEED",
    }
    raw = json.dumps(
        [base | {"source_row_id": "row-test-1"}, base | {"source_row_id": "row-test-2"}]
    ).encode()
    endpoint, args = request_for(query)
    parsed = parse_external(raw, query, str(httpx.URL(endpoint, params=args)))
    assert [r["key"] for r in parsed.records] == ["row-test-1", "row-test-2"]
    assert all(r["body"]["document_amount"] == "0" for r in parsed.records)
    old = validate_query("nyc_acris", query["params"], limit=2, adapter_version="iges-public-sources/1")
    endpoint, args = request_for(old)
    replay = parse_external(json.dumps([base]).encode(), old, str(httpx.URL(endpoint, params=args)))
    assert replay.records[0]["key"] == "EXPLICIT_TEST_DOCUMENT"


def test_market_connector_is_labelled_not_accepted_as_original_http():
    query = validate_query(
        "alpaca_stock_bars", {"symbols": "JPM", "start": "2024-01-02", "end": "2024-01-03"}
    )
    endpoint, args = request_for(query)
    body = {
        "tool": "get_stock_bars",
        "request": {
            "symbols": ["JPM"],
            "start": "2024-01-02",
            "end": "2024-01-03",
            "feed": "iex",
            "timeframe": "1Day",
            "limit": 100,
        },
        "counts": {"records": 1},
        "bars": {
            "JPM": [
                {
                    "timestamp": "2024-01-02T05:00:00+00:00",
                    "open": 1.125,
                    "high": 2,
                    "low": 1,
                    "close": 1.5,
                    "volume": 10,
                }
            ]
        },
    }
    result = parse_external(
        json.dumps(body).encode(), query, str(httpx.URL(endpoint, params=args)), "MCP_TOOL"
    )
    assert "connector normalization" in result.coverage["capture"]
    assert result.records[0]["body"]["adjustment"] == "unspecified_by_connector"
    assert result.records[0]["body"]["trade_count"] is None
    body["bars"]["JPM"][0]["low"] = 3
    with pytest.raises(ValueError):
        parse_external(json.dumps(body).encode(), query, str(httpx.URL(endpoint, params=args)), "MCP_TOOL")


def test_http_rejects_redirects_html_and_missing_market_credentials(monkeypatch):
    original = httpx.AsyncClient
    for status, headers in [(302, {"Location": "http://localhost"}), (200, {"Content-Type": "text/html"})]:
        transport = httpx.MockTransport(
            lambda request, status=status, headers=headers: httpx.Response(
                status, headers=headers, content=b"<html>TEST CONTROL</html>"
            )
        )
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda transport=transport, **kwargs: original(**kwargs, transport=transport),
        )
        with pytest.raises((ValueError, httpx.HTTPError)):
            asyncio.run(fetch_external("fdic_institutions", {}, limit=1))
    monkeypatch.delenv("IGES_ALPACA_DATA_KEY", raising=False)
    monkeypatch.delenv("IGES_ALPACA_DATA_SECRET", raising=False)
    with pytest.raises(ValueError, match="CREDENTIALS_REQUIRED"):
        asyncio.run(fetch_external("alpaca_stock_bars", {}))


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("IGES_TEST_ADMIN_URL"), reason="disposable PostgreSQL required")
def test_external_api_idempotence_access_admission_and_raw_replay(monkeypatch):
    from app import external_api

    identity = {"sub": "EXPLICIT_SOURCE_TEST_ACTOR", "roles": ["ingestor", "analyst", "editor"]}
    app.dependency_overrides[verified_identity] = lambda: identity
    snap = snapshot(fixture_raw(uuid4().hex))
    calls = []

    async def fake_fetch(*args):
        calls.append(args)
        return snap

    monkeypatch.setattr(external_api, "fetch_external", fake_fetch)
    try:
        with TestClient(app) as client:
            payload = {"dataset": "fdic_institutions", "limit": 1}
            headers = {"Idempotency-Key": uuid4().hex}
            response = client.post("/v1/sources/ingest", json=payload, headers=headers)
            assert response.status_code == 201, response.text
            result = response.json()
            assert client.post("/v1/sources/ingest", json=payload, headers=headers).json() == result
            assert len(calls) == 1
            assert (
                client.post("/v1/sources/ingest", json=payload | {"page": 2}, headers=headers).status_code
                == 409
            )
            eid = result["evidence_id"]
            original = client.get(f"/v1/sources/batches/{eid}/original")
            assert original.content == snap.raw
            assert original.headers["X-Content-SHA256"] == snap.sha256
            records = client.get(f"/v1/sources/batches/{eid}/records").json()["records"]
            assert len(records) == 1 and records[0]["provenance_state"] == "UNASSESSED"
            case = client.post(
                "/v1/cases",
                json={
                    "title": "EXPLICIT SOURCE TEST FIXTURE",
                    "scope": "EXPLICIT TEST: not an actual research case",
                    "period_from": "2024-01-01",
                    "period_to": "2024-12-31",
                    "jurisdictions": ["US"],
                },
                headers={"Idempotency-Key": uuid4().hex},
            ).json()
            admission = client.post(
                f"/v1/cases/{case['id']}/source-admissions",
                json={"evidence_id": eid},
                headers={"Idempotency-Key": uuid4().hex, "If-Match": f'"{case["case_revision"]}"'},
            )
            assert admission.status_code == 201, admission.text
            assert admission.json()["status"] == "PENDING"
            assert (
                client.get(f"/v1/cases/{case['id']}/documents/{admission.json()['id']}/original").status_code
                == 409
            )
            identity["roles"] = ["reader"]
            assert (
                client.post(
                    "/v1/sources/ingest", json=payload, headers={"Idempotency-Key": uuid4().hex}
                ).status_code
                == 403
            )
            assert client.get(f"/v1/sources/batches/{eid}/records").status_code == 200
            assert client.get(f"/v1/sources/batches/{eid}/original").status_code == 403
            app.dependency_overrides.clear()
            assert client.get("/v1/sources/catalog").status_code in {401, 503}
        checked = verify_integrity()
        assert checked["external_source_records_checked"] >= 1
        with tenant_session() as session:
            assert store_external(session, snap, "EXPLICIT_SOURCE_TEST_ACTOR")["created"] is False
        # Runtime cannot mutate source records. Administrator tampering is detected and restored in this fixture only.
        admin = create_engine(os.environ["IGES_TEST_ADMIN_URL"])
        try:
            with tenant_session() as session:
                assert (
                    session.execute(
                        text(
                            "SELECT has_table_privilege(current_user,'source_records','UPDATE,DELETE,TRUNCATE')"
                        )
                    ).scalar_one()
                    is False
                )
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE source_records SET body='{}'::jsonb WHERE evidence_id=:id AND project_id=:pid"
                    ),
                    {"id": eid, "pid": str(settings.project_id)},
                )
            with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
                verify_integrity()
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text("UPDATE source_records SET body=CAST(:body AS jsonb) WHERE evidence_id=:id"),
                    {"body": canonical(snap.records[0]["body"]), "id": eid},
                )
            admin.dispose()
    finally:
        app.dependency_overrides.clear()
