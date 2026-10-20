import hashlib
import json
from decimal import Decimal

import pytest

from app.worldbank import MAX_BYTES, parse_snapshot, validate_request


def fixture_raw(country="PRT", indicator="SP.POP.TOTL", year="2024", value=12345):
    return json.dumps([
        {"page": 1, "pages": 1, "total": 1},
        [{"countryiso3code": country, "indicator": {"id": indicator},
          "date": year, "value": value, "obs_status": ""}],
    ]).encode()


def test_canonical_source_hash_and_exact_locator():
    body = fixture_raw()
    snap = parse_snapshot(body, "https://api.worldbank.org/test", "PRT", "SP.POP.TOTL", 2024, 2024)
    assert snap.sha256 == hashlib.sha256(body).hexdigest()
    assert snap.raw == body
    assert snap.observations[0].locator == "$[1][0]"
    assert snap.observations[0].value == Decimal("12345")


def test_null_value_is_not_imputed():
    snap = parse_snapshot(
        fixture_raw(value=None), "https://api.worldbank.org/test",
        "PRT", "SP.POP.TOTL", 2024, 2024,
    )
    assert snap.observations[0].value is None


def test_wrong_country_is_rejected():
    with pytest.raises(ValueError, match="mismatched"):
        parse_snapshot(fixture_raw(country="UKR"), "x", "PRT", "SP.POP.TOTL", 2024, 2024)


def test_duplicate_year_is_rejected():
    doc = json.loads(fixture_raw())
    doc[1].append(dict(doc[1][0]))
    with pytest.raises(ValueError, match="duplicate"):
        parse_snapshot(json.dumps(doc).encode(), "x", "PRT", "SP.POP.TOTL", 2024, 2024)


def test_fake_api_error_and_payload_bomb():
    with pytest.raises(ValueError, match="envelope"):
        parse_snapshot(b'{"message":"error"}', "x", "PRT", "SP.POP.TOTL", 2024, 2024)
    with pytest.raises(ValueError, match="maximum size"):
        parse_snapshot(b"x" * (MAX_BYTES + 1), "x", "PRT", "SP.POP.TOTL", 2024, 2024)


def test_allowlist_blocks_arbitrary_paths():
    with pytest.raises(ValueError, match="allowlisted"):
        validate_request("PRT", "../../private/file", 2021, 2024)
    with pytest.raises(ValueError, match="ISO"):
        validate_request("P/T", "SP.POP.TOTL", 2021, 2024)


def test_out_of_range_period_rejected():
    with pytest.raises(ValueError, match="out-of-range"):
        parse_snapshot(fixture_raw(year="1999"), "x", "PRT", "SP.POP.TOTL", 2024, 2024)


def test_non_finite_numeric_rejected():
    doc = json.loads(fixture_raw())
    doc[1][0]["value"] = "NaN"
    with pytest.raises(ValueError, match="non-finite"):
        parse_snapshot(json.dumps(doc).encode(), "x", "PRT", "SP.POP.TOTL", 2024, 2024)
