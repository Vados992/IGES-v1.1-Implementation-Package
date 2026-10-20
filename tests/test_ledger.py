from decimal import Decimal

import pytest

from app.ledger import stage_totals


def test_budget_not_counted_as_disbursement():
    totals = stage_totals([
        {"stage": "APPROPRIATION", "amount": "100.00"},
        {"stage": "COMMITMENT", "amount": "100.00"},
        {"stage": "DISBURSEMENT", "amount": "30.00"},
        {"stage": "RECEIPT", "amount": "30.00"},
    ])
    assert Decimal(totals["DISBURSEMENT"]) == Decimal("30.00")
    assert Decimal(totals["RECEIPT"]) == Decimal("30.00")
    assert Decimal(totals["APPROPRIATION"]) == Decimal("100.00")


def test_refunds_and_reversals_are_separate():
    totals = stage_totals([
        {"stage": "DISBURSEMENT", "amount": "45"},
        {"stage": "REFUND", "amount": "5"},
        {"stage": "REVERSAL", "amount": "2"},
    ])
    assert Decimal(totals["DISBURSEMENT"]) == 45
    assert Decimal(totals["REFUND"]) == 5
    assert Decimal(totals["REVERSAL"]) == 2


@pytest.mark.parametrize("stage,amount", [
    ("CONTROL", "10"), ("DISBURSEMENT", "-2"),
    ("CONTRACT", "NaN"), ("CONTRACT", "Infinity"),
])
def test_invalid_events_rejected(stage, amount):
    with pytest.raises(ValueError):
        stage_totals([{"stage": stage, "amount": amount}])
