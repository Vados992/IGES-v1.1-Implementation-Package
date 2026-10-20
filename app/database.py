"""Tenant-scoped database transactions. Single-project pilot only.

The custom PostgreSQL GUC is NOT a substitute for cryptographically bound
multi-tenant authorization: upgrading to multi-project service requires
independently assessed tenant-isolation controls.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = None
factory = None


def _factory():
    global engine, factory
    if factory is None:
        if not settings.database_url:
            raise RuntimeError("IGES_DATABASE_URL is not configured")
        engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory


@contextmanager
def tenant_session() -> Iterator[Session]:
    with _factory()() as session:
        with session.begin():
            session.execute(
                text("SELECT set_config('iges.project_id', :project_id, true)"),
                {"project_id": str(settings.project_id)},
            )
            yield session
