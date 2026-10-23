"""OIDC authorization for privileged endpoints; absence of configuration denies access."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit
import time
import ssl

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.config import settings

bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=2)
def _jwks_client(url: str) -> PyJWKClient:
    context = ssl.create_default_context(cafile=settings.oidc_ca_file)
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5, ssl_context=context)


def https_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.fragment)
    except ValueError:
        return False


def verify_mfa(payload: dict) -> None:
    """Trust only signed provider assertions, never a client-supplied MFA header."""
    if not settings.oidc_require_mfa:
        return
    amr = payload.get("amr")
    if not isinstance(amr, list) or not all(isinstance(method, str) for method in amr):
        raise HTTPException(status_code=403, detail="MFA_REQUIRED")
    methods = set(amr)
    if "mfa" not in methods and not {"pwd", "otp"}.issubset(methods):
        raise HTTPException(status_code=403, detail="MFA_REQUIRED")
    if settings.oidc_required_acr and payload.get("acr") != settings.oidc_required_acr:
        raise HTTPException(status_code=403, detail="AUTHENTICATION_CONTEXT_REQUIRED")
    auth_time = payload.get("auth_time")
    if (type(auth_time) is not int or auth_time > time.time() + 20
            or time.time() - auth_time > settings.oidc_max_auth_age):
        raise HTTPException(status_code=403, detail="RECENT_AUTHENTICATION_REQUIRED")


def verified_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if not all((settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url)):
        raise HTTPException(status_code=503, detail="OIDC_NOT_CONFIGURED")
    if not (
        https_endpoint(settings.oidc_issuer)
        and https_endpoint(settings.oidc_jwks_url)
    ):
        raise HTTPException(status_code=503, detail="OIDC_HTTPS_REQUIRED")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="BEARER_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
    if len(credentials.credentials) > 16384:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")
    try:
        key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(credentials.credentials)
        payload = jwt.decode(
            credentials.credentials,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
            leeway=20,
        )
        if not isinstance(payload.get("sub"), str) or not 1 <= len(payload["sub"].strip()) <= 255:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN")
        if str(payload.get("project_id", "")) != str(settings.project_id):
            raise HTTPException(status_code=403, detail="PROJECT_DENIED")
        roles = payload.get('roles', [])
        if not isinstance(roles, list) or len(roles) > 50 or any(not isinstance(role, str) or len(role) > 100 for role in roles):
            raise HTTPException(status_code=403, detail='INVALID_ROLE_CLAIMS')
        verify_mfa(payload)
        return payload
    except HTTPException:
        raise
    except (PyJWTError, ValueError, TypeError, KeyError, OSError):
        raise HTTPException(status_code=401, detail="INVALID_TOKEN") from None


def require_role(role: str, *additional: str):
    def _required(identity: dict = Depends(verified_identity)) -> dict:
        roles = identity.get("roles", [])
        if not isinstance(roles, list) or not any(allowed in roles for allowed in (role, *additional)):
            raise HTTPException(status_code=403, detail="ROLE_DENIED")
        return identity

    return _required
