"""Narrow, auditable World Bank API adapter. No general-purpose URL fetching."""
from __future__ import annotations

import hashlib
import re
import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.source_json import MAX_BYTES, load_source_json

ALLOWED_INDICATORS = frozenset({
    "SP.POP.TOTL",
    "NY.GDP.MKTP.CD",
    "GC.DOD.TOTL.GD.ZS",
})
COUNTRY_PATTERN = re.compile(r"^[A-Z]{3}$")


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
        raise ValueError("country must be a three-letter uppercase World Bank economy code (ISO-style)")
    if indicator not in ALLOWED_INDICATORS:
        raise ValueError("indicator is not allowlisted")
    if not (1960 <= start <= end <= 2100) or end - start > 30:
        raise ValueError("year range must be within 1960..2100 and at most 31 years")


def parse_snapshot(raw: bytes, url: str, country: str, indicator: str, start: int, end: int) -> Snapshot:
    validate_request(country, indicator, start, end)
    payload = load_source_json(raw)
    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
        raise ValueError("unexpected World Bank response envelope")
    rows = payload[1]
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
        if raw_value is not None and not isinstance(raw_value, Decimal):
            raise ValueError("non-finite or invalid numeric type")
        try:
            value = None if raw_value is None else Decimal(str(raw_value))
        except InvalidOperation as exc:
            raise ValueError("invalid numeric value") from exc
        if value is not None and not value.is_finite():
            raise ValueError("non-finite numeric value")
        status = row.get("obs_status")
        if status is not None and (not isinstance(status, str) or len(status) > 100):
            raise ValueError("invalid observation status")
        result.append(Observation(code, indicator, year, value, str(status) if status else None, f"$[1][{i}]"))
    if not result:
        raise ValueError("source response contained zero observations")
    meta = payload[0]
    if (not isinstance(meta, dict) or meta.get("page") != 1 or meta.get("pages") != 1
            or meta.get("total") != len(rows)):
        raise ValueError("incomplete or invalid pagination metadata")
    return Snapshot(url, raw, hashlib.sha256(raw).hexdigest(), tuple(result))


async def fetch_snapshot(country: str, indicator: str, start: int, end: int) -> Snapshot:
    # An overall deadline also bounds a slow response that never hits a read timeout.
    async with asyncio.timeout(30):
        return await _fetch_snapshot(country, indicator, start, end)


async def _fetch_snapshot(country: str, indicator: str, start: int, end: int) -> Snapshot:
    validate_request(country, indicator, start, end)
    url = (
        f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
        f"?format=json&date={start}:{end}&per_page=100"
    )
    chunks = bytearray()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=False) as client:
        async with client.stream("GET", url, headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("unexpected redirect or response")
            if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise ValueError("unexpected media type")
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("compressed response is not accepted")
            async for chunk in response.aiter_raw():
                if len(chunks) + len(chunk) > MAX_BYTES:
                    raise ValueError("source response exceeds maximum size")
                chunks.extend(chunk)
    return parse_snapshot(bytes(chunks), url, country, indicator, start, end)
