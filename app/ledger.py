"""Financial lifecycle invariants, never infer transfers from commitments."""
from __future__ import annotations

from decimal import Decimal

STAGES = frozenset({
    "COMMITMENT", "APPROPRIATION", "OBLIGATION", "CONTRACT",
    "DISBURSEMENT", "RECEIPT", "EXPENDITURE", "REFUND", "REVERSAL",
})


def stage_totals(events: list[dict]) -> dict[str, str]:
    """Aggregate by mutually exclusive event stage.

    A disbursement and the corresponding receipt are two perspectives on a
    transfer, not two independently additive disbursements. Refund/reversal
    records are reported separately rather than silently netted.
    """
    totals = {stage: Decimal("0") for stage in STAGES}
    for event in events:
        stage = event["stage"]
        if stage not in STAGES:
            raise ValueError("unknown financial stage")
        amount = Decimal(str(event["amount"]))
        if not amount.is_finite() or amount < 0:
            raise ValueError("invalid amount")
        totals[stage] += amount
    return {key: str(value) for key, value in sorted(totals.items())}
