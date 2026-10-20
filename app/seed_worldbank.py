"""Trusted operator-only CLI to fetch actual publicly available records."""
from __future__ import annotations

import argparse
import asyncio
import json

from app.database import tenant_session
from app.persistence import store_snapshot
from app.worldbank import ALLOWED_INDICATORS, fetch_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Import real World Bank records with provenance")
    parser.add_argument("--country", required=True)
    parser.add_argument("--indicator", required=True, choices=sorted(ALLOWED_INDICATORS))
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--end", required=True, type=int)
    args = parser.parse_args()
    snapshot = asyncio.run(fetch_snapshot(args.country, args.indicator, args.start, args.end))
    with tenant_session() as session:
        evidence_id, count, created = store_snapshot(session, snapshot, "TRUSTED_LOCAL_OPERATOR")
    print(json.dumps({
        "source": snapshot.url, "sha256": snapshot.sha256,
        "evidence_id": evidence_id, "records_inserted": count,
        "new_snapshot": created, "status": "UNASSESSED",
    }, indent=2))


if __name__ == "__main__":
    main()
