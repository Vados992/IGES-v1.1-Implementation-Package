"""OIDC authorization for privileged endpoints; absence of configuration denies access."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.config import settings

bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=2)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


def https_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.fragment)
    except ValueError:
        return False


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
        return payload
    except HTTPException:
        raise
    except (PyJWTError, ValueError, KeyError, OSError):
        raise HTTPException(status_code=401, detail="INVALID_TOKEN") from None


def require_role(role: str):
    def _required(identity: dict = Depends(verified_identity)) -> dict:
        roles = identity.get("roles", [])
        if not isinstance(roles, list) or role not in roles:
            raise HTTPException(status_code=403, detail="ROLE_DENIED")
        return identity

    return _required
