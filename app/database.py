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
from app.migrate import SCHEMA_VERSION

engine = None
factory = None
_init_lock = Lock()
PROTECTED_TABLES = (
    "projects", "evidence", "observations", "public_awards", "financial_events", "claims",
    "reviews", "audit_events", "evidence_attestations",
)


def check_database(session: Session) -> None:
    version = session.execute(text("SELECT version FROM schema_version")).scalar_one()
    project_count = session.execute(text("SELECT count(*) FROM projects")).scalar_one()
    unsafe = session.execute(text(
        "SELECT rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole "
        "FROM pg_roles WHERE rolname=current_user")).scalar_one()
    protections = session.execute(text(
        "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,"
        "has_table_privilege(current_user,c.oid,'UPDATE,DELETE,TRUNCATE') AS mutable "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(:tables)"),
        {"tables": list(PROTECTED_TABLES)}).all()
    if (version != SCHEMA_VERSION or project_count != 1 or unsafe
            or len(protections) != len(PROTECTED_TABLES)
            or any(not row.relrowsecurity or not row.relforcerowsecurity or row.mutable for row in protections)):
        raise RuntimeError("schema, role, project, RLS or append-only permissions not ready")


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
