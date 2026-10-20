"""Financial lifecycle invariants, never infer transfers from commitments."""
from __future__ import annotations

from decimal import Decimal, localcontext

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
    currencies = {event.get("currency") for event in events}
    if len(currencies) > 1:
        raise ValueError("totals require one currency")
    totals = {stage: Decimal("0") for stage in STAGES}
    with localcontext() as ctx:
        ctx.prec = 80
        for event in events:
            stage = event["stage"]
            if stage not in STAGES:
                raise ValueError("unknown financial stage")
            amount = Decimal(str(event["amount"]))
            if not amount.is_finite() or amount < 0 or abs(amount.adjusted()) > 40:
                raise ValueError("invalid amount")
            totals[stage] += amount
    return {key: str(value) for key, value in sorted(totals.items())}
