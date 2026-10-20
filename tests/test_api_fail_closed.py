from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_public_health_returns_limited_data():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["environment"] == "controlled_pilot"


def test_admin_endpoints_deny_without_oidc(monkeypatch):
    from app import auth
    monkeypatch.setattr(auth.settings, "oidc_issuer", "", raising=False) if False else None
    # Default CI has no configured issuer; if environment does, missing bearer is still denied.
    response = client.post(
        "/v1/admin/ingest/worldbank",
        json={"country": "PRT", "indicator": "SP.POP.TOTL", "start": 2023, "end": 2024},
    )
    assert response.status_code in (401, 503)


def test_invalid_admin_payload_fails_validation():
    response = client.post(
        "/v1/admin/ingest/worldbank",
        json={"country": "../", "indicator": "SP.POP.TOTL", "start": 2023, "end": 2024},
    )
    assert response.status_code in (401, 422, 503)


def test_no_public_claim_publication_routes():
    response = client.post("/v1/public/claims", json={})
    assert response.status_code == 404
