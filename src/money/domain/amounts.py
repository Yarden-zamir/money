"""Money arithmetic.

Every amount in this system is a `Decimal` quantized to two places. Floats are never used:
a budget that disagrees with itself by an agora because of binary rounding is a bug the user
would have to reconcile by hand.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class AmountError(ValueError):
    """An amount could not be parsed or does not satisfy a constraint."""


def parse_amount(value: str | int | Decimal) -> Decimal:
    """Parse an external amount into a quantized Decimal.

    Floats are rejected outright rather than coerced, because accepting one would silently
    reintroduce the imprecision this module exists to avoid.
    """
    if isinstance(value, float):
        raise AmountError(f"amounts must not be floats, got {value!r}")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise AmountError(f"not a valid amount: {value!r}") from exc
    if not parsed.is_finite():
        raise AmountError(f"amount must be finite, got {value!r}")
    return quantize(parsed)


def quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def format_amount(value: Decimal) -> str:
    """Serialize for YAML and JSON. Always two places, so diffs stay stable."""
    return f"{quantize(value):.2f}"


def allocate(total: Decimal, ratios: dict[str, Decimal]) -> dict[str, Decimal]:
    """Split `total` across `ratios` so the parts sum to exactly `total`.

    Ratios must sum to 1. Each part is rounded to the agora, then the rounding remainder is
    given to the largest ratio, which keeps the sum exact without spreading a visible
    distortion across every share. Ties go to the first key, so the result is deterministic
    for a given input order.
    """
    if not ratios:
        raise AmountError("cannot allocate across an empty set of ratios")
    if any(isinstance(r, float) for r in ratios.values()):
        raise AmountError("split ratios must be Decimal, not float")

    ratio_sum = sum(ratios.values(), start=Decimal(0))
    if ratio_sum != Decimal(1):
        raise AmountError(f"split ratios must sum to 1, got {ratio_sum}")
    if any(r < 0 for r in ratios.values()):
        raise AmountError("split ratios must not be negative")

    total = quantize(total)
    parts = {key: quantize(total * ratio) for key, ratio in ratios.items()}

    drift = total - sum(parts.values(), start=ZERO)
    if drift != ZERO:
        # max() returns the first maximal element, which gives ties to the first key.
        largest = max(ratios, key=lambda key: ratios[key])
        parts[largest] = quantize(parts[largest] + drift)

    return parts


def sums_to(parts: list[Decimal], expected: Decimal) -> bool:
    return sum(parts, start=ZERO) == quantize(expected)
