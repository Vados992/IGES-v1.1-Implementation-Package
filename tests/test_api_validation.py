from fastapi.testclient import TestClient

from app.auth import verified_identity
from app.main import app


def test_body_limit_and_security_headers():
    with TestClient(app) as client:
        response = client.post("/v1/admin/claims", content=b"x" * 65537)
        assert response.status_code == 413
        assert response.headers["x-content-type-options"] == "nosniff"


def test_authenticated_validation_before_database():
    app.dependency_overrides[verified_identity] = lambda: {"sub": "tester", "roles": ["ingestor", "analyst"]}
    try:
        with TestClient(app) as client:
            response = client.post("/v1/admin/ingest/worldbank", json={
                "country": "PRT", "indicator": "SP.POP.TOTL", "start": 2024, "end": 2023})
            assert response.status_code == 422
            response = client.post("/v1/admin/claims", json={
                "statement": " " * 30, "evidence_id": "00000000-0000-4000-8000-000000000001"})
            assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
