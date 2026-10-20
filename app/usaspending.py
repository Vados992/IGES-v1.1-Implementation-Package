"""Official USAspending award-search adapter.

Award totals are NOT represented as cash disbursements.
See https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
MAX_BYTES = 2_000_000


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
    if not (2008 <= fiscal_year <= 2026):
        raise ValueError("fiscal year outside allowlisted range")
    if not 1 <= limit <= 25:
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
    if len(raw) > MAX_BYTES:
        raise ValueError("response exceeds 2 MB limit")
    data = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("invalid USAspending response envelope")
    rows = data["results"]
    if len(rows) > request["limit"]:
        raise ValueError("upstream exceeded result limit")
    page = data.get("page_metadata", {})
    if not isinstance(page, dict):
        raise ValueError("invalid pagination metadata")
    seen = set()
    parsed = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict) or "internal_id" not in row:
            raise ValueError("missing authoritative award key")
        source_key = str(row["internal_id"])
        if source_key in seen:
            raise ValueError("duplicate award key within response")
        seen.add(source_key)
        raw_amount = row.get("Award Amount")
        try:
            amount = None if raw_amount is None else Decimal(str(raw_amount))
        except InvalidOperation as exc:
            raise ValueError("invalid award amount") from exc
        if amount is not None and (not amount.is_finite() or amount.adjusted() >= 28):
            raise ValueError("award amount outside numeric bounds")
        parsed.append(Award(
            key=source_key,
            award_id=str(row["Award ID"]) if row.get("Award ID") is not None else None,
            recipient=str(row["Recipient Name"]) if row.get("Recipient Name") is not None else None,
            awarding_agency=str(row["Awarding Agency"]) if row.get("Awarding Agency") is not None else None,
            funding_agency=str(row["Funding Agency"]) if row.get("Funding Agency") is not None else None,
            amount=amount,
            locator=f"$.results[{idx}]",
        ))
    return AwardSnapshot(
        url=url, request=request, raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        request_sha256=hashlib.sha256(canonical_request(request)).hexdigest(),
        awards=tuple(parsed), has_next_page=bool(page.get("hasNext", False)),
    )


async def fetch_awards(fiscal_year: int, limit: int) -> AwardSnapshot:
    body = build_request(fiscal_year, limit)
    chunks = bytearray()
    async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
        async with client.stream(
            "POST", URL, headers={"Content-Type": "application/json", "Accept": "application/json"},
            content=canonical_request(body),
        ) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("unexpected redirect or response")
            async for chunk in response.aiter_bytes():
                if len(chunks) + len(chunk) > MAX_BYTES:
                    raise ValueError("upstream response too large")
                chunks.extend(chunk)
    return parse_awards(bytes(chunks), body)
