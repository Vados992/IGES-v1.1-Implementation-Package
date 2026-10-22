import hashlib
import json
from decimal import Decimal

import pytest

from app.usaspending import build_request, canonical_request, parse_awards


def sample(amount=1000):
    return json.dumps({
        "spending_level": "awards",
        "limit": 2,
        "results": [{
            "internal_id": 1234,
            "Award ID": "ABCD001",
            "Recipient Name": "Company Example",
            "Awarding Agency": "Agency Example",
            "Funding Agency": "Agency Example",
            "Award Amount": amount,
        }],
        "page_metadata": {"page": 1, "hasNext": True},
    }).encode()


def test_contracts_date_bounds_and_fixed_allowlist():
    request = build_request(2024, 2)
    assert request["filters"]["award_type_codes"] == ["A", "B", "C", "D"]
    assert request["filters"]["time_period"][0]["start_date"] == "2023-10-01"
    assert request["page"] == 1


def test_provenance_and_obligation_not_disbursement():
    body = build_request(2024, 2)
    record = parse_awards(sample(), body)
    assert record.sha256 == hashlib.sha256(record.raw).hexdigest()
    assert record.request_sha256 == hashlib.sha256(canonical_request(body)).hexdigest()
    assert record.awards[0].amount == Decimal(1000)
    assert record.awards[0].locator == "$.results[0]"
    assert record.has_next_page is True


def test_unknown_award_key_rejected():
    raw = json.loads(sample())
    del raw["results"][0]["internal_id"]
    with pytest.raises(ValueError, match="key"):
        parse_awards(json.dumps(raw).encode(), build_request(2024, 2))


def test_disallow_arbitrary_year_and_excessive_page():
    with pytest.raises(ValueError, match="fiscal year"):
        build_request(2050, 2)
    with pytest.raises(ValueError, match="limit"):
        build_request(2024, 500)


def test_non_finite_amount_rejected():
    raw = json.loads(sample())
    raw["results"][0]["Award Amount"] = "NaN"
    with pytest.raises(ValueError, match="numeric bounds"):
        parse_awards(json.dumps(raw).encode(), build_request(2024, 2))
