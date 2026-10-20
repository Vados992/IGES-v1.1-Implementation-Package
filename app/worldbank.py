"""Narrow, auditable World Bank API adapter. No general-purpose URL fetching."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

ALLOWED_INDICATORS = frozenset({
    "SP.POP.TOTL",
    "NY.GDP.MKTP.CD",
    "GC.DOD.TOTL.GD.ZS",
})
COUNTRY_PATTERN = re.compile(r"^[A-Z]{3}$")
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Observation:
    country: str
    indicator: str
    year: int
    value: Decimal | None
    status: str | None
    locator: str


@dataclass(frozen=True)
class Snapshot:
    url: str
    raw: bytes
    sha256: str
    observations: tuple[Observation, ...]


def validate_request(country: str, indicator: str, start: int, end: int) -> None:
    if not COUNTRY_PATTERN.fullmatch(country):
        raise ValueError("country must be a three-letter uppercase ISO code")
    if indicator not in ALLOWED_INDICATORS:
        raise ValueError("indicator is not allowlisted")
    if not (1960 <= start <= end <= 2100) or end - start > 30:
        raise ValueError("year range must be within 1960..2100 and at most 31 years")


def parse_snapshot(raw: bytes, url: str, country: str, indicator: str, start: int, end: int) -> Snapshot:
    validate_request(country, indicator, start, end)
    if len(raw) > MAX_BYTES:
        raise ValueError("source response exceeds maximum size")
    payload = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
        raise ValueError("unexpected World Bank response envelope")
    if not isinstance(payload[0], dict) or int(payload[0].get('pages', 1)) != 1:\n        raise ValueError('source response pagination is incomplete')\n    rows = payload[1]
    if len(rows) > 100:
        raise ValueError("response has excessive observation count")
    result = []
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("invalid observation object")
        code = row.get("countryiso3code")
        ind = row.get("indicator")
        year_text = row.get("date")
        if code != country or not isinstance(ind, dict) or ind.get("id") != indicator:
            raise ValueError("source returned mismatched country or indicator")
        if not isinstance(year_text, str) or not re.fullmatch(r"[0-9]{4}", year_text):
            raise ValueError("unexpected period format")
        year = int(year_text)
        if not start <= year <= end or year in seen:
            raise ValueError("duplicate or out-of-range year")
        seen.add(year)
        raw_value = row.get("value")
        try:
            value = None if raw_value is None else Decimal(str(raw_value))
        except InvalidOperation as exc:
            raise ValueError("invalid numeric value") from exc
        if value is not None and not value.is_finite():
            raise ValueError("non-finite numeric value")
        if value is not None and value.adjusted() >= 28:\n            raise ValueError('source numeric value exceeds database precision')\n        status = row.get("obs_status")
        result.append(Observation(code, indicator, year, value, str(status) if status else None, f"$[1][{i}]"))
    if not result:
        raise ValueError("source response contained zero observations")
    return Snapshot(url, raw, hashlib.sha256(raw).hexdigest(), tuple(result))


async def fetch_snapshot(country: str, indicator: str, start: int, end: int) -> Snapshot:
    validate_request(country, indicator, start, end)
    url = (
        f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
        f"?format=json&date={start}:{end}&per_page=100"
    )
    chunks = bytearray()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=False) as client:
        async with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("unexpected redirect or response")
            async for chunk in response.aiter_bytes():
                if len(chunks) + len(chunk) > MAX_BYTES:
                    raise ValueError("source response exceeds maximum size")
                chunks.extend(chunk)
    return parse_snapshot(bytes(chunks), url, country, indicator, start, end)
