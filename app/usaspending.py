"""Official USAspending award-search adapter.

Award totals are NOT represented as cash disbursements.
See https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md
"""
from __future__ import annotations

import hashlib
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.source_json import MAX_BYTES, load_source_json

URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
MAX_FISCAL_YEAR = datetime.now(timezone.utc).year


@dataclass(frozen=True)
class Award:
    key: str
    award_id: str | None
    recipient: str | None
    awarding_agency: str | None
    funding_agency: str | None
    amount: Decimal | None
    locator: str


@dataclass(frozen=True)
class AwardSnapshot:
    url: str
    request: dict
    raw: bytes
    sha256: str
    request_sha256: str
    awards: tuple[Award, ...]
    has_next_page: bool


def build_request(fiscal_year: int, limit: int) -> dict:
    if type(fiscal_year) is not int or not (2008 <= fiscal_year <= MAX_FISCAL_YEAR):
        raise ValueError("fiscal year outside allowlisted range")
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("limit must be 1..25")
    return {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{
                "start_date": f"{fiscal_year - 1}-10-01",
                "end_date": f"{fiscal_year}-09-30",
            }],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "Funding Agency",
        ],
        "sort": "Award Amount",
        "order": "desc",
        "page": 1,
        "limit": limit,
        "subawards": False,
    }


def canonical_request(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_awards(raw: bytes, request: dict, url: str = URL) -> AwardSnapshot:
    if url != URL or request != build_request(int(request["filters"]["time_period"][0]["end_date"][:4]), request["limit"]):
        raise ValueError("unexpected source request")
    data = load_source_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("invalid USAspending response envelope")
    rows = data["results"]
    if len(rows) > request["limit"]:
        raise ValueError("upstream exceeded result limit")
    page = data.get("page_metadata", {})
    if (not isinstance(page, dict) or not isinstance(page.get("page"), Decimal) or page.get("page") != 1
            or type(page.get("hasNext")) is not bool):
        raise ValueError("invalid pagination metadata")
    if data.get("spending_level") != "awards" or data.get("limit") != request["limit"]:
        raise ValueError("unexpected search scope or result limit")
    seen = set()
    parsed = []
    for idx, row in enumerate(rows):
        if (not isinstance(row, dict) or not isinstance(row.get("internal_id"), Decimal)
                or row["internal_id"] != row["internal_id"].to_integral_value()
                or not 0 < row["internal_id"] < 10**30):
            raise ValueError("missing authoritative award key")
        source_key = str(int(row["internal_id"]))
        if source_key in seen:
            raise ValueError("duplicate award key within response")
        seen.add(source_key)
        raw_amount = row.get("Award Amount")
        if raw_amount is not None and not isinstance(raw_amount, Decimal):
            raise ValueError("award amount outside numeric bounds")
        try:
            amount = None if raw_amount is None else Decimal(str(raw_amount))
        except InvalidOperation as exc:
            raise ValueError("invalid award amount") from exc
        if amount is not None and (not amount.is_finite() or amount.adjusted() >= 28):
            raise ValueError("award amount outside numeric bounds")
        def optional_text(name):
            value = row.get(name)
            if value is not None and (not isinstance(value, str) or len(value) > 5000):
                raise ValueError("invalid award text field")
            return value

        parsed.append(Award(
            key=source_key,
            award_id=optional_text("Award ID"), recipient=optional_text("Recipient Name"),
            awarding_agency=optional_text("Awarding Agency"), funding_agency=optional_text("Funding Agency"),
            amount=amount,
            locator=f"$.results[{idx}]",
        ))
    return AwardSnapshot(
        url=url, request=request, raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        request_sha256=hashlib.sha256(canonical_request(request)).hexdigest(),
        awards=tuple(parsed), has_next_page=page["hasNext"],
    )


async def fetch_awards(fiscal_year: int, limit: int) -> AwardSnapshot:
    async with asyncio.timeout(45):
        return await _fetch_awards(fiscal_year, limit)


async def _fetch_awards(fiscal_year: int, limit: int) -> AwardSnapshot:
    body = build_request(fiscal_year, limit)
    chunks = bytearray()
    async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
        async with client.stream(
            "POST", URL, headers={"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity"},
            content=canonical_request(body),
        ) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("unexpected redirect or response")
            if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise ValueError("unexpected media type")
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("compressed response is not accepted")
            async for chunk in response.aiter_raw():
                if len(chunks) + len(chunk) > MAX_BYTES:
                    raise ValueError("upstream response too large")
                chunks.extend(chunk)
    return parse_awards(bytes(chunks), body)
