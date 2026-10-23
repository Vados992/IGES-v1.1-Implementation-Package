"""Explicit control fixtures only, never inserted into the real source corpus."""

import hashlib
import asyncio
import json
import os

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, text

from app.auth import verified_identity
from app.database import tenant_session
from app.external_persistence import store_external, store_collection_attempt
from app.external_sources import fetch_external, parse_external, request_for, response_bound, validate_query
from app.main import app
from app.verify_integrity import verify_integrity


def roster():
    return [
        {
            "id": 123,
            "convocation": 9,
            "nreg": "mp-test1_skl9",
            "full_name": "ТЕСТОВИЙ КОНТРОЛЬНИЙ ЗАПИС",
            "date_begin": "2019-08-29",
            "date_end": None,
            "birthday": "1900-01-01",
            "address": "EXPLICIT_PRIVATE_FIXTURE_NOT_FOR_INDEX",
        }
    ]


def parse(dataset, raw, params=None):
    q = validate_query(dataset, params or {})
    url, args = request_for(q)
    return parse_external(raw, q, str(httpx.URL(url, params=args)))


def cec():
    return (
        '<?xml version="1.0" encoding="windows-1251"?>'
        '<result><region id="5" name="ТЕСТОВА ОБЛАСТЬ"><rada id="1" name="ТЕСТОВА РАДА">'
        "<head/><deputies><deputy><PIB>КОНТРОЛЬНИЙ ЗАПИС</PIB><DN>01.01.1900</DN>"
        "<F63>PRIVATE_FIXTURE_ADDRESS</F63><F13>PRIVATE_FIXTURE_MEMBERSHIP</F13>"
        "<PROCESS>Місцеві вибори 25.10.2020</PROCESS><DATE_OF_APPOINTMENT>06.11.2020</DATE_OF_APPOINTMENT>"
        "</deputy></deputies></rada></region></result>"
    ).encode("cp1251")


def test_roster_minimization_duplicates_and_source_dates():
    source = roster()
    snap = parse("ua_rada_roster", json.dumps(source * 2).encode())
    assert len(snap.records) == 2
    assert len({r["key"] for r in snap.records}) == 2
    assert snap.coverage["repeated_card_id_rows"] == 1
    body = snap.records[0]["body"]
    assert body["mandate_end"] is None
    assert body["search_name"] == body["name"].casefold()
    assert "birthday" not in body and "address" not in body
    assert body["current_office_status"] != "CURRENT"
    with pytest.raises(ValueError, match="CONVOCATION"):
        parse("ua_rada_roster", json.dumps(source).encode(), {"term": "8"})
    source[0].update(convocation=7, nreg="mp-test1_skl7", date_begin="2012-12-12", date_end="2013-12-31")
    old = parse("ua_rada_roster", json.dumps(source).encode(), {"term": "7"})
    assert old.records == () and old.coverage["excluded_ended_before_2014"] == 1


def test_cec_xml_encoding_empty_heads_dates_and_private_fields():
    snap = parse("ua_cec_elected_2020", cec())
    assert snap.coverage["excluded_empty_head_elements"] == 1
    assert snap.coverage["role_counts"] == {"deputy": 1, "head": 0}
    assert snap.records[0]["body"]["election_decision_date"] == "2020-11-06"
    assert snap.records[0]["body"]["person_identifier"] is None
    assert snap.records[0]["locator"] == "/result/region[1]/rada[1]/deputies/deputy[1]"
    assert "PRIVATE_FIXTURE" not in json.dumps(snap.records)
    for invalid in [
        b'<!DOCTYPE result [<!ENTITY x SYSTEM "file:///private">]><result>&x;</result>',
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE result><result/>'.encode("utf-16"),
        cec().replace(b"<PIB>", b"<UNREVIEWED_FIELD>"),
    ]:
        with pytest.raises(ValueError):
            parse("ua_cec_elected_2020", invalid)
    with pytest.raises(ValueError, match="NOT_PAGED"):
        validate_query("ua_cec_elected_2020", {}, page=2)
    assert response_bound("fdic_institutions") == 2_000_000
    assert response_bound("ua_cec_elected_2020") == 32_000_000


def test_posts_retain_unknown_time_and_do_not_infer_history():
    snap = parse(
        "ua_rada_posts", b"mp_id,full_name,post_name,unit_name,post_title\n123,EXPLICIT TEST,POST,ORG,TITLE\n"
    )
    assert snap.records[0]["body"]["mandate_start"] is None
    assert snap.coverage["date_coverage"] == "NO_POST_DATE_RANGES_IN_SOURCE"
    with pytest.raises(ValueError):
        parse("ua_rada_posts", b"mp_id,full_name,post_name,unit_name,post_title,unreviewed\n")


def test_rada_transport_retry_repeats_same_request_without_fallback(monkeypatch):
    import app.external_sources as module

    original_client = httpx.AsyncClient
    seen = []

    class FixtureStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(roster()).encode()

    def handler(request):
        seen.append(str(request.url))
        if len(seen) == 1:
            raise httpx.ConnectError("EXPLICIT_TEST_TRANSPORT_FAILURE", request=request)
        return httpx.Response(
            200, stream=FixtureStream(), headers={"content-type": "application/json"}
        )

    async def no_delay(seconds):
        assert seconds == 10

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(module.asyncio, "sleep", no_delay)
    snap = asyncio.run(fetch_external("ua_rada_roster", {}))
    assert len(snap.records) == 1
    assert len(seen) == 2 and seen[0] == seen[1]


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("IGES_TEST_ADMIN_URL"), reason="disposable PostgreSQL required")
def test_private_search_original_gate_and_attempt_chain():
    snap = parse("ua_rada_roster", json.dumps(roster()).encode())
    with tenant_session() as session:
        saved = store_external(session, snap, "EXPLICIT_UKRAINE_TEST")
        attempt = {
            "dataset": "EXPLICIT_TEST_AVAILABILITY",
            "status": "UNAVAILABLE",
            "http_status": 403,
            "records_imported": 0,
            "response_sha256": hashlib.sha256(b"TEST_BODY").hexdigest(),
        }
        aid = store_collection_attempt(session, attempt, "EXPLICIT_UKRAINE_TEST")
    app.dependency_overrides[verified_identity] = lambda: {"sub": "EXPLICIT_TEST_READER", "roles": ["reader"]}
    try:
        with TestClient(app) as client:
            result = client.get("/v1/sources/ukraine/search", params={"q": "тестовий контрольний"})
            assert result.status_code == 200
            assert result.json()["records"][0]["provenance_state"] == "UNASSESSED"
            assert "PRIVATE_FIXTURE" not in result.text
            assert client.get("/v1/sources/ukraine/search", params={"q": "%_TEST"}).json()["records"] == []
            assert client.get("/v1/sources/ukraine/coverage").json()["universe_complete"] is False
            assert client.get(f"/v1/sources/batches/{saved['evidence_id']}/original").status_code == 403
            app.dependency_overrides[verified_identity] = lambda: {
                "sub": "EXPLICIT_TEST_ANALYST",
                "roles": ["analyst"],
            }
            assert client.get(f"/v1/sources/batches/{saved['evidence_id']}/original").status_code == 403
            app.dependency_overrides[verified_identity] = lambda: {
                "sub": "EXPLICIT_TEST_COUNSEL",
                "roles": ["counsel"],
            }
            actual = client.get(f"/v1/sources/batches/{saved['evidence_id']}/original")
            assert actual.content == snap.raw
            assert actual.headers["x-content-sha256"] == snap.sha256
        assert verify_integrity()["source_collection_attempts_checked"] >= 1
        admin = create_engine(os.environ["IGES_TEST_ADMIN_URL"])
        try:
            with admin.begin() as connection:
                connection.execute(
                    text("UPDATE source_collection_attempts SET body='{}'::jsonb WHERE id=:id"), {"id": aid}
                )
            with pytest.raises(ValueError, match="COLLECTION_ATTEMPT"):
                verify_integrity()
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text("UPDATE source_collection_attempts SET body=CAST(:body AS jsonb) WHERE id=:id"),
                    {"body": json.dumps(attempt), "id": aid},
                )
            admin.dispose()
    finally:
        app.dependency_overrides.clear()
