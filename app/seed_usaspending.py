"""Trusted CLI importer for real USAspending federal procurement awards."""
from __future__ import annotations

import argparse
import asyncio
import json

from app.database import tenant_session
from app.persistence import store_awards
from app.usaspending import fetch_awards


def main():
    parser = argparse.ArgumentParser(description="Import official public USAspending award records")
    parser.add_argument("--fiscal-year", required=True, type=int)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    snapshot = asyncio.run(fetch_awards(args.fiscal_year, args.limit))
    with tenant_session() as session:
        evidence_id, count, created = store_awards(session, snapshot, "TRUSTED_LOCAL_OPERATOR")
    print(json.dumps({
        "source": snapshot.url, "request_sha256": snapshot.request_sha256,
        "content_sha256": snapshot.sha256, "evidence_id": evidence_id,
        "awards_inserted": count, "new_snapshot": created,
        "has_next_page": snapshot.has_next_page,
        "status": "UNASSESSED",
        "interpretation": "Award amount is not a cash payment or ultimate-use record",
    }, indent=2))


if __name__ == "__main__":
    main()
