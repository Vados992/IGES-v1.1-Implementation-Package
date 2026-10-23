"""Explicit administrator-only v2/v3/v4/v5 -> v6 migration; startup never migrates."""
import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

SCHEMA_VERSION = 6
MIGRATIONS = Path(__file__).resolve().parents[1] / 'db/migrations'


def upgrade(connection):
    connection.execute(text("SELECT pg_advisory_xact_lock(914031003)"))
    version = connection.execute(text("SELECT version FROM schema_version")).scalar_one()
    if version == SCHEMA_VERSION:
        return False
    if version not in (2, 3, 4, 5):
        raise RuntimeError("Only a verified schema v2, v3, v4 or v5 database can be upgraded")
    if version == 2:
        connection.exec_driver_sql((MIGRATIONS / '003_award_provenance.sql').read_text(encoding='utf-8'),
                                   execution_options={'no_parameters': True})
    if version < 4:
        connection.exec_driver_sql((MIGRATIONS / '004_evidence_workflow.sql').read_text(encoding='utf-8'),
                                   execution_options={'no_parameters': True})
    if version < 5:
        connection.exec_driver_sql((MIGRATIONS / '005_workspace_revisions.sql').read_text(encoding='utf-8'),
                               execution_options={'no_parameters': True})
    connection.exec_driver_sql((MIGRATIONS / '006_external_sources.sql').read_text(encoding='utf-8'),
                               execution_options={'no_parameters': True})
    return True


def main():
    parser = argparse.ArgumentParser(description="Administrator-only schema migration; take a backup first")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = os.getenv("IGES_MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("Set IGES_MIGRATION_DATABASE_URL using administrator credentials")
    engine = create_engine(url, connect_args={"connect_timeout": 5, "options": "-c lock_timeout=10000 -c statement_timeout=60000"})
    try:
        with engine.begin() as connection:
            changed = upgrade(connection) if args.apply else False
            version = connection.execute(text("SELECT version FROM schema_version")).scalar_one()
        print(json.dumps({"schema_version": version, "migration_applied": changed}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
