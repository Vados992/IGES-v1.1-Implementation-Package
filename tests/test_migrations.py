"""Rehearse a non-destructive v2 -> v3 upgrade in a separate disposable database."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.migrate import upgrade
from app.persistence import append_audit
from test_worldbank import fixture_raw

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.getenv("IGES_TEST_ADMIN_URL"), reason="disposable PostgreSQL required")]


def test_v2_upgrade_preserves_source_and_audit():
    name = "iges_upgrade_" + uuid4().hex
    url = make_url(os.environ["IGES_TEST_ADMIN_URL"])
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    migrated = None
    with admin.connect() as owner:
        owner.exec_driver_sql(f'CREATE DATABASE "{name}"')
        try:
            migrated = create_engine(url.set(database=name))
            legacy = (Path(__file__).parent / "schema-v2.template").read_text()
            legacy = "\n".join(line for line in legacy.splitlines()
                               if not line.startswith(("\\set", "CREATE ROLE iges_runtime ")))
            legacy = legacy.replace(":'project_id'", "'" + str(settings.project_id) + "'")
            legacy = legacy.replace(":DBNAME", '"' + name + '"')
            with migrated.begin() as connection:
                connection.exec_driver_sql(legacy)
            raw = fixture_raw(value=None)
            eid = str(uuid4())
            source = "https://api.worldbank.org/v2/country/PRT/indicator/SP.POP.TOTL?format=json&date=2024:2024&per_page=100"
            with Session(migrated) as session, session.begin():
                session.execute(text("SELECT set_config('iges.project_id',:pid,true)"), {"pid": str(settings.project_id)})
                session.execute(text("INSERT INTO evidence(id,project_id,provider,source_url,content_sha256,raw_bytes) "
                                     "VALUES (:id,:pid,'WORLD_BANK',:url,:sha,:raw)"),
                                {"id": eid, "pid": str(settings.project_id), "url": source,
                                 "sha": hashlib.sha256(raw).hexdigest(), "raw": raw})
                append_audit(session, "MIGRATION_TEST", "SOURCE_RECEIVED", eid)
            with migrated.begin() as connection:
                before = dict(connection.execute(text("SELECT * FROM evidence")).mappings().one())
                audit_before = dict(connection.execute(text("SELECT * FROM audit_events")).mappings().one())
                assert upgrade(connection) is True
                assert upgrade(connection) is False
                after = dict(connection.execute(text("SELECT * FROM evidence")).mappings().one())
                assert {key: after[key] for key in before} == before
                assert dict(connection.execute(text("SELECT * FROM audit_events")).mappings().one()) == audit_before
                assert after["request_sha256"] == hashlib.sha256(("GET " + source).encode()).hexdigest()
                assert connection.execute(text("SELECT version FROM schema_version")).scalar_one() == 3
                protected = connection.execute(text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname='public_awards'"
                )).scalar_one()
                assert protected is True
        finally:
            if migrated is not None:
                migrated.dispose()
            owner.exec_driver_sql(f'DROP DATABASE "{name}"')
    admin.dispose()
