"""Locally signed tokens, no issuer network traffic or production secrets."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import auth


@pytest.fixture
def signer(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, "settings", replace(auth.settings, oidc_issuer="https://issuer.example",
                                                 oidc_audience="iges", oidc_jwks_url="https://issuer.example/jwks"))
    monkeypatch.setattr(auth, "_jwks_client", lambda url: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private.public_key())))

    def token(**changes):
        payload = {"sub": "reviewer-1", "iss": "https://issuer.example", "aud": "iges",
                   "exp": int(datetime.now(timezone.utc).timestamp()) + 300,
                   "project_id": str(auth.settings.project_id), "roles": ["reviewer"],
                   "amr": ["pwd", "otp"], "auth_time": int(datetime.now(timezone.utc).timestamp())}
        payload.update(changes)
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(payload, private, algorithm="RS256"))
    return token


def test_valid_signed_identity_and_role(signer):
    payload = auth.verified_identity(signer())
    assert auth.require_role("reviewer")(payload)["sub"] == "reviewer-1"


@pytest.mark.parametrize("change,status", [
    ({"exp": 1}, 401), ({"aud": "other"}, 401), ({"iss": "https://other.example"}, 401),
    ({"project_id": "other"}, 403), ({"sub": " "}, 401), ({"sub": None}, 401),
    ({"exp": None}, 401), ({"exp": []}, 401), ({"aud": None}, 401),
])
def test_invalid_signed_identity_denied(signer, change, status):
    with pytest.raises(HTTPException) as error:
        auth.verified_identity(signer(**change))
    assert error.value.status_code == status


def test_bad_signature_denied(signer):
    credentials = signer()
    part = credentials.credentials.split(".")
    part[-1] = ("A" if part[-1][0] != "A" else "B") + part[-1][1:]
    with pytest.raises(HTTPException) as error:
        auth.verified_identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials=".".join(part)))
    assert error.value.status_code == 401


@pytest.mark.parametrize("roles", [[], "reviewer", None, ["analyst"]])
def test_role_denied(roles):
    with pytest.raises(HTTPException) as error:
        auth.require_role("reviewer")({"roles": roles})
    assert error.value.status_code == 403


def test_missing_bearer_is_401_with_configured_issuer(signer):
    with pytest.raises(HTTPException) as error:
        auth.verified_identity(None)
    assert error.value.status_code == 401


@pytest.mark.parametrize("url", ["http://issuer.example", "https://", "https://user:pass@example.com", "https://example.com/#fragment"])
def test_invalid_https_endpoint(url):
    assert not auth.https_endpoint(url)


@pytest.mark.parametrize("amr", [None, "mfa", [], ["pwd"], ["otp"], ["hwk"], [True], [{}]])
def test_single_factor_tokens_are_denied(signer, amr):
    with pytest.raises(HTTPException) as error:
        auth.verified_identity(signer(amr=amr))
    assert error.value.detail == "MFA_REQUIRED"


@pytest.mark.parametrize("auth_time", [None, 1, True, "123", 9999999999])
def test_stale_or_invalid_authentication_is_denied(signer, auth_time):
    with pytest.raises(HTTPException) as error:
        auth.verified_identity(signer(auth_time=auth_time))
    assert error.value.detail == "RECENT_AUTHENTICATION_REQUIRED"


def test_provider_mfa_assertion_is_accepted(signer):
    assert auth.verified_identity(signer(amr=["mfa"]))["sub"] == "reviewer-1"


def test_configured_context_is_required(signer, monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, oidc_required_acr="iges-mfa"))
    with pytest.raises(HTTPException) as error:
        auth.verified_identity(signer(acr="password-only"))
    assert error.value.detail == "AUTHENTICATION_CONTEXT_REQUIRED"
    assert auth.verified_identity(signer(acr="iges-mfa"))["acr"] == "iges-mfa"
