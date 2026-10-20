"""Tenant-scoped database transactions. Single-project pilot only.

The custom PostgreSQL GUC is NOT a substitute for cryptographically bound
multi-tenant authorization: upgrading to multi-project service requires
independently assessed tenant-isolation controls.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from threading import Lock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = None
factory = None
_init_lock = Lock()


def _factory():
    global engine, factory
    with _init_lock:
        if factory is None:
            if not settings.database_url:
                raise RuntimeError("IGES_DATABASE_URL is not configured")
            engine = create_engine(
                settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                connect_args={"connect_timeout": 5, "options": "-c statement_timeout=15000 -c lock_timeout=10000"},
            )
            factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory


@contextmanager
def tenant_session(*, read_only: bool = False, repeatable_read: bool = False) -> Iterator[Session]:
    with _factory()() as session:
        with session.begin():
            if repeatable_read:
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            if read_only:
                session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(
                text("SELECT set_config('iges.project_id', :project_id, true)"),
                {"project_id": str(settings.project_id)},
            )
            yield session
