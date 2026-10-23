"""Back up and migrate only this task's isolated source corpus, preserving its records and pilot."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.migrate import upgrade

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "work/source-corpus"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    info = json.loads((STATE / "cluster.json").read_text())
    cluster = Path(info["cluster"]).resolve()
    name = info["database"]
    if (
        not cluster.is_relative_to(ROOT / "work")
        or not re.fullmatch(r"iges_sources_[a-f0-9]{32}", name)
        or info["port"] != 55434
    ):
        raise RuntimeError("Refusing to operate outside this task's source corpus")
    admin = make_url(json.loads((cluster / "test-environment.json").read_text())["IGES_TEST_ADMIN_URL"])
    runtime = make_url(json.loads((STATE / "environment.json").read_text())["IGES_DATABASE_URL"])
    if admin.host != "127.0.0.1" or admin.port != 55434 or runtime.database != name:
        raise RuntimeError("Corpus database binding mismatch")
    target = admin.set(database=name)
    backup = STATE / ("before-migration-" + uuid4().hex + ".dump")
    executable = args.pg_bin.resolve() / ("pg_dump.exe" if os.name == "nt" else "pg_dump")
    # Fixed argv, no shell; password is environment-only and is not printed.
    subprocess.run(  # noqa: S603 - administrator-selected PostgreSQL binary, fixed argv, no shell
        [
            str(executable),
            "--host",
            target.host,
            "--port",
            str(target.port),  # noqa: S603
            "--username",
            target.username,
            "--dbname",
            name,
            "--format=c",
            "--file",
            str(backup),
        ],
        check=True,
        env={**os.environ, "PGPASSWORD": target.password},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    engine = create_engine(target)
    try:
        with engine.begin() as connection:

            def fingerprint():
                return connection.execute(
                    text(
                        "SELECT count(*),md5(string_agg(id::text||content_sha256||request_sha256,',' ORDER BY id)) FROM evidence"
                    )
                ).one()

            before = fingerprint()
            changed = upgrade(connection)
            if fingerprint() != before:
                raise RuntimeError("Migration changed original evidence fingerprints")
        receipt = {
            "database": name,
            "migration_applied": changed,
            "evidence_count_preserved": before[0],
            "backup_file": backup.name,
            "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        }
        (STATE / (backup.stem + ".json")).write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt), flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
