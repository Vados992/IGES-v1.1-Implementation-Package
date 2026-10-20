"""Settings: all secrets are runtime-provided, never bundled."""
from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.engine import URL


@dataclass(frozen=True)
class Settings:
    database_url: str
    project_id: UUID
    oidc_issuer: str
    oidc_audience: str
    oidc_jwks_url: str
    oidc_require_mfa: bool = True
    oidc_required_acr: str = ""
    oidc_max_auth_age: int = 900
    oidc_ca_file: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        mfa_setting = os.getenv("IGES_OIDC_REQUIRE_MFA", "true").lower()
        if mfa_setting not in {"true", "false"}:
            raise ValueError("IGES_OIDC_REQUIRE_MFA must be true or false")
        max_auth_age = int(os.getenv("IGES_OIDC_MAX_AUTH_AGE", "900"))
        if not 60 <= max_auth_age <= 3600:
            raise ValueError("IGES_OIDC_MAX_AUTH_AGE must be within 60..3600 seconds")
        database_url = os.getenv("IGES_DATABASE_URL", "")
        if not database_url and os.getenv("IGES_DB_PASSWORD"):
            database_url = URL.create(
                "postgresql+psycopg", username="iges_runtime",
                password=os.environ["IGES_DB_PASSWORD"],
                host=os.getenv("IGES_DB_HOST", "db"), port=5432, database=os.getenv("IGES_DB_NAME", "iges"),
            ).render_as_string(hide_password=False)
        return cls(
            database_url=database_url,
            project_id=UUID(os.getenv("IGES_PUBLIC_PROJECT_ID", "00000000-0000-4000-8000-000000000001")),
            oidc_issuer=os.getenv("IGES_OIDC_ISSUER", ""),
            oidc_audience=os.getenv("IGES_OIDC_AUDIENCE", ""),
            oidc_jwks_url=os.getenv("IGES_OIDC_JWKS_URL", ""),
            oidc_require_mfa=mfa_setting == "true",
            oidc_required_acr=os.getenv("IGES_OIDC_REQUIRED_ACR", ""),
            oidc_max_auth_age=max_auth_age,
            oidc_ca_file=os.getenv("IGES_OIDC_CA_FILE") or None,
        )


settings = Settings.from_env()
