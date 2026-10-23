"""Bounded official API availability receipts. No unreviewed declaration/body ingestion."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json

import httpx

from app.database import tenant_session
from app.external_persistence import store_collection_attempt

ENDPOINT = "https://public-api.nazk.gov.ua/v2/documents/list"


async def probe(year):
    if type(year) is not int or not 2015 <= year <= min(2026, datetime.now(timezone.utc).year):
        raise ValueError("NAZK_REPORT_YEAR_OUT_OF_RANGE")
    params = {"declaration_year": str(year), "workPlace": "Верховна Рада", "page": "1"}
    receipt = {
        "dataset": "ua_nazk_registry_availability",
        "reporting_year": year,
        "request_url": str(httpx.URL(ENDPOINT, params=params)),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "http_status": None,
        "response_sha256": None,
        "records_imported": 0,
        "meaning": "Workplace search is not politician identity verification; no declaration contents imported",
    }
    try:
        async with asyncio.timeout(40):
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream(
                    "GET",
                    ENDPOINT,
                    params=params,
                    headers={"Accept-Encoding": "identity", "User-Agent": "IGES-official-public-data/1.1"},
                ) as response:
                    receipt["http_status"] = response.status_code
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > 2_000_000:
                            raise ValueError("NAZK_RESPONSE_BOUND")
                        body.extend(chunk)
                    receipt["response_sha256"] = hashlib.sha256(body).hexdigest()
                    receipt["status"] = (
                        "AVAILABLE_NOT_IMPORTED_SCHEMA_AND_PRIVACY_REVIEW_REQUIRED"
                        if response.status_code == 200
                        and response.headers.get("content-type", "").startswith("application/json")
                        else "UNAVAILABLE_HTTP_OR_MEDIA_TYPE"
                    )
    except Exception as error:
        receipt.update(status="UNAVAILABLE_NETWORK_OR_SIZE", error_class=type(error).__name__)
    with tenant_session() as session:
        receipt_id = store_collection_attempt(session, receipt, "CONTROLLED_OFFICIAL_API_AVAILABILITY_CHECK")
    return {"attempt_id": receipt_id, **receipt}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append")
    args = parser.parse_args()
    for year in args.year or range(2015, min(2026, datetime.now(timezone.utc).year) + 1):
        print(json.dumps(await probe(year), ensure_ascii=False), flush=True)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
