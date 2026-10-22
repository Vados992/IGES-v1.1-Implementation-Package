"""Operator-controlled bounded imports; each page is durable, original-backed and resumable."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from app.database import tenant_session
from app.external_catalog import DATASETS
from app.external_persistence import store_external
from app.external_sources import fetch_external, parse_external, request_for, validate_query


async def run(dataset, params, pages=1, limit=100, start_page=1, connector=None):
    receipts = []
    keys = set()
    status = "BOUNDED"
    failure = None
    prior_index = None
    prior_total = None
    for page in range(start_page, start_page + pages):
        try:
            if connector:
                if (
                    dataset != "alpaca_stock_bars"
                    or pages != 1
                    or page != 1
                    or connector.stat().st_size > 2_000_000
                ):
                    raise ValueError("INVALID_CONNECTOR_IMPORT")
                q = validate_query(dataset, params, page, limit)
                endpoint, args = request_for(q)
                snapshot = parse_external(
                    connector.read_bytes(), q, str(httpx.URL(endpoint, params=args)), "MCP_TOOL"
                )
            else:
                snapshot = await fetch_external(dataset, params, page, limit)
            page_keys = {r["key"] for r in snapshot.records}
            index = snapshot.coverage.get("provider_index") or snapshot.coverage.get("golden_copy")
            total = snapshot.coverage.get("reported_total")
            if receipts and (
                (prior_index and index != prior_index) or (prior_total is not None and total != prior_total)
            ):
                raise ValueError("PROVIDER_VINTAGE_CHANGED_DURING_PAGING")
            prior_index, prior_total = index, total
            if keys & page_keys:
                raise ValueError("DUPLICATE_KEYS_ACROSS_SOURCE_PAGES")
            keys |= page_keys
            if len(keys) > 50_000:
                raise ValueError("BULK_RECORD_BOUND")
            with tenant_session() as session:
                result = store_external(session, snapshot, "CONTROLLED_PUBLIC_SOURCE_IMPORT")
            receipts.append({"page": page, **result})
            if not snapshot.has_more:
                status = "QUERY_EXHAUSTED" if not connector else "CONNECTOR_SLICE_ONLY"
                break
            await asyncio.sleep(0.25)
        except Exception as error:
            # Prior committed pages remain available; failure is explicit, never replaced by examples.
            status = "PARTIAL_FAILURE" if receipts else "FAILED"
            failure = type(error).__name__
            if isinstance(error, ValueError):
                failure = str(error)[:100]
            break
    return {
        "dataset": dataset,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "records_seen": len(keys),
        "records_inserted": sum(r["records_inserted"] for r in receipts),
        "pages": receipts,
        "failure": failure,
        "meaning": "Actual attributed source records; no finding/independent approval; prior pages retained on failure",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--param", action="append", default=[])
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument(
        "--connector",
        type=Path,
        help="Exact Alpaca get_stock_bars MCP text envelope, labelled connector-normalized",
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    params = {}
    for item in args.param:
        key, sep, value = item.partition("=")
        if not sep or key in params:
            parser.error("Parameters must be unique name=value pairs")
        params[key] = value
    if not 1 <= args.pages <= 100 or not 1 <= args.start_page <= 100 or args.start_page + args.pages > 101:
        parser.error("Bounded page range is 1..100")
    validate_query(args.dataset, params, args.start_page, args.limit)
    result = asyncio.run(run(args.dataset, params, args.pages, args.limit, args.start_page, args.connector))
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["failure"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
