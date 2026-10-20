"""Settings: all secrets are runtime-provided, never bundled."""
from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    database_url: str
    project_id: UUID
    oidc_issuer: str
    oidc_audience: str
    oidc_jwks_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("IGES_DATABASE_URL", ""),
            project_id=UUID(os.getenv("IGES_PUBLIC_PROJECT_ID", "00000000-0000-4000-8000-000000000001")),
            oidc_issuer=os.getenv("IGES_OIDC_ISSUER", ""),
            oidc_audience=os.getenv("IGES_OIDC_AUDIENCE", ""),
            oidc_jwks_url=os.getenv("IGES_OIDC_JWKS_URL", ""),
        )


settings = Settings.from_env()
