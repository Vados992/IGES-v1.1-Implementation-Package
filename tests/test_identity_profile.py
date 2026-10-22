import pytest

from app.config import Settings
from scripts.windows_pilot import realm
from scripts import keycloak_validate


def test_windows_identity_requires_real_factors_and_pkce():
    profile = realm({"project_id": "00000000-0000-4000-8000-000000000001", "operator_password": "temporary-test-password"})
    flow = next(flow for flow in profile["authenticationFlows"] if flow["alias"] == profile["browserFlow"])
    assert {(item["authenticator"], item["requirement"]) for item in flow["authenticationExecutions"]} == {
        ("auth-username-password-form", "REQUIRED"), ("auth-otp-form", "REQUIRED")}
    client = profile["clients"][0]
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["directAccessGrantsEnabled"] is False
    assert client["serviceAccountsEnabled"] is False
    assert profile["users"][0]["requiredActions"] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
    web = next(client for client in profile['clients'] if client['clientId'] == 'iges-web')
    assert web['attributes']['pkce.code.challenge.method'] == 'S256'
    assert web['directAccessGrantsEnabled'] is False
    assert web['serviceAccountsEnabled'] is False
    assert 'https://localhost:8444/workspace' in web['redirectUris']
    assert 'https://localhost:8444' in web['webOrigins']


@pytest.mark.parametrize("value", ["0", "-1", "59", "3601", "not-a-number"])
def test_invalid_authentication_freshness_rejected(monkeypatch, value):
    monkeypatch.setenv("IGES_OIDC_MAX_AUTH_AGE", value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_otp_matches_rfc_vector(monkeypatch):
    monkeypatch.setattr(keycloak_validate.time, "time", lambda: 59)
    assert keycloak_validate.totp("12345678901234567890") == "287082"
