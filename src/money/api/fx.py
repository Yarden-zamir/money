"""Turning "convert this" into an `Fx` block, for every route that creates or converts.

Three sources for a rate, in the order a person would want them: the one they typed, the one
already in the repo's table for that day, and the provider. The provider's answer is handed
back as a row so the caller commits it beside the entry — the table is written only by the
same commit that used it, so a repo never holds a rate nothing depends on.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from money.api.deps import BudgetContext
from money.api.errors import ApiError
from money.api.rates import fetch_rate
from money.domain.amounts import quantize
from money.domain.models import Fx, parse_rate
from money.store.store import RateRow


def resolve_rate(
    context: BudgetContext, currency: str, day: date
) -> tuple[Decimal | None, str, RateRow | None]:
    """(rate, where it came from, row to commit). `table` rows need no commit."""
    known = context.store.rate(currency, day)
    if known is not None:
        return known, "table", None
    fetched = fetch_rate(currency, context.store.budget().currency, day)
    if fetched is None:
        return None, "none", None
    return fetched, "provider", (day, currency, fetched)


def conversion(
    context: BudgetContext,
    *,
    currency: str,
    amount: Decimal,
    day: date,
    rate: Decimal | None,
) -> tuple[Fx, RateRow | None]:
    """The `Fx` for `amount` of `currency`, at a typed `rate` or the day's rate.

    Refuses rather than guesses when no rate can be found: the caller can keep the entry
    unconverted, which is a state the app understands, whereas a made-up rate is not.
    """
    if rate is not None:
        typed = parse_rate(rate)
        return Fx(rate=typed, amount=quantize(amount * typed), at=day, source="manual"), None

    found, source, row = resolve_rate(context, currency, day)
    if found is None:
        raise ApiError(
            "no_rate",
            f"no exchange rate for {currency} on {day.isoformat()}; "
            "type one, or keep the entry unconverted",
            status=422,
            details={"currency": currency, "date": day.isoformat()},
        )
    return Fx(rate=found, amount=quantize(amount * found), at=day, source="table"), row
