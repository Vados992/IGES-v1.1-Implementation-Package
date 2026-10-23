"""Create/populate a separate real-public-data database inside this task's isolated test cluster."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "work/source-corpus"


def initialize(env_file):
    path = env_file.resolve()
    if not path.is_relative_to(ROOT / "work") or (STATE / "environment.json").exists():
        raise RuntimeError(
            "Only a new corpus in this task ignored work/ is allowed; existing data are preserved"
        )
    original = json.loads(path.read_text())
    url = make_url(original["IGES_TEST_ADMIN_URL"])
    if url.host != "127.0.0.1" or url.port != 55434:
        raise RuntimeError("Refusing to use the installed pilot or an external database")
    name = "iges_sources_" + uuid4().hex
    cluster = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with cluster.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        cluster.dispose()
    project = str(uuid4())
    target = create_engine(url.set(database=name))
    template = (ROOT / "db/init/01_schema.template").read_text()
    template = "\n".join(
        line for line in template.splitlines() if not line.startswith(("\\set", "CREATE ROLE iges_runtime "))
    )
    template = template.replace(":'project_id'", "'" + project + "'").replace(":DBNAME", '"' + name + '"')
    try:
        with target.begin() as connection:
            connection.exec_driver_sql(template, execution_options={"no_parameters": True})
            for migration in sorted((ROOT / "db/migrations").glob("*.sql")):
                connection.exec_driver_sql(migration.read_text(), execution_options={"no_parameters": True})
    finally:
        target.dispose()
    environment = {
        "IGES_DATABASE_URL": make_url(original["IGES_DATABASE_URL"])
        .set(database=name)
        .render_as_string(hide_password=False),
        "IGES_PUBLIC_PROJECT_ID": project,
    }
    STATE.mkdir(parents=True)
    (STATE / "environment.json").write_text(json.dumps(environment))
    (STATE / "cluster.json").write_text(
        json.dumps({"cluster": str(path.parent), "database": name, "port": 55434})
    )
    print(
        json.dumps(
            {
                "initialized": True,
                "database": name,
                "classification": "Only actual public-source imports; no test findings/approvals/identities inserted",
            }
        ),
        flush=True,
    )


async def import_plan(plan):
    from app.seed_external import run

    items = json.loads(plan.read_text())
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("Bounded source plan required")
    reports = []
    for index, item in enumerate(items):
        result = await run(
            item["dataset"],
            item.get("params", {}),
            item.get("pages", 1),
            item.get("limit", 100),
            start_page=item.get("start_page", 1),
            connector=Path(item["connector"]) if item.get("connector") else None,
        )
        (STATE / f"{index:03d}-{item['dataset']}.receipt.json").write_text(json.dumps(result, indent=2))
        reports.append(result)
        print(
            json.dumps(
                {
                    "dataset": result["dataset"],
                    "status": result["status"],
                    "records_seen": result["records_seen"],
                    "records_inserted": result["records_inserted"],
                    "failure": result["failure"],
                }
            ),
            flush=True,
        )
    from app.verify_integrity import verify_integrity

    verified = verify_integrity()
    report = {
        "plan": str(plan),
        "datasets": reports,
        "integrity": verified,
        "all_source_queries_succeeded": all(not r["failure"] for r in reports),
    }
    (STATE / "verification.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {"integrity": verified, "all_source_queries_succeeded": report["all_source_queries_succeeded"]}
        ),
        flush=True,
    )
    if not report["all_source_queries_succeeded"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize-from", type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    if args.initialize_from:
        initialize(args.initialize_from)
    os.environ.update(json.loads((STATE / "environment.json").read_text()))
    if args.plan:
        asyncio.run(import_plan(args.plan))
    else:
        from app.verify_integrity import verify_integrity

        print(json.dumps(verify_integrity()), flush=True)


if __name__ == "__main__":
    main()
