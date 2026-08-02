"""Guessing what someone is about to type.

Every suggestion is drawn from this budget's own history — nothing is inferred from other
users, and nothing is invented. The point is to pre-fill the entry a person was going to
make anyway, and to be able to say exactly why, so a wrong guess is obvious rather than
mysterious.

Signals, strongest first:

1. **Payee**, when they have already chosen one. It is the most specific thing they can say,
   so it overrides everything else.
2. **Place**, within a short radius. Being at the same coffee shop is a strong signal.
3. **Time pattern** — the same weekday, and the same part of the day when the entry recorded
   one. Saturday-evening shopping looks like other Saturday evenings, not like a Tuesday
   lunch.

The amount is the *mode* when one repeats, because a coffee costs the same every time. When
every past visit differs the mean is meaningless — you bought different things — so the most
recent is offered instead. Which rule fired is returned with the answer.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

from money.domain.amounts import ZERO
from money.domain.models import Entry, EntryKind, LineItem, Share

# How close counts as "the same place". Wide enough to survive phone GPS drift indoors,
# narrow enough not to merge neighbouring shops on a high street.
SAME_PLACE_METRES = 120.0

# Part of the day, when the entry knows one. An entry that was back-dated or imported has no
# recorded clock time, and inventing one would make it match a slot it never happened in — so
# those match on weekday alone and simply compare against a coarser bucket.
EVENING_FROM = 17
MORNING_UNTIL = 11


class Suggestion(BaseModel):
    """A guessed entry, with the reasoning attached."""

    payee: str | None = None
    amount: Decimal | None = None
    bucket: str | None = None
    shares: list[Share] = Field(default_factory=list)
    items: list[LineItem] = Field(default_factory=list)
    place_name: str | None = None

    confidence: float = Field(ge=0, le=1)
    basis: str = Field(description="Which signal fired: payee, place, time, or none")
    reason: str = Field(description="Human-readable explanation, shown on hover")
    sample_size: int = 0


def distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Haversine is far more precision than 120m needs, but it is
    short and has no edge cases near the date line or the poles."""
    radius = 6_371_000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def time_slot(when: datetime | date) -> str:
    """The habit's granularity: the weekday, plus the part of day when one is known.

    A plain `date` yields the weekday alone. Comparing a coarse slot against a fine one is
    handled by `slots_match`, so an entry with no clock time still matches its weekday.
    """
    if isinstance(when, datetime):
        part = (
            "morning"
            if when.hour < MORNING_UNTIL
            else "evening"
            if when.hour >= EVENING_FROM
            else "midday"
        )
        return f"weekday-{when.weekday()}-{part}"
    return f"weekday-{when.weekday()}"


def slots_match(query: str, stored: str) -> bool:
    """Whether two slots describe the same habit.

    An entry with no clock time carries only a weekday, so it matches any part of that day
    rather than being excluded — a coarser record should still be usable, just less specific.
    """
    if query == stored:
        return True
    return query.split("-")[1] == stored.split("-")[1] and (
        len(query.split("-")) == 2 or len(stored.split("-")) == 2
    )


def suggest(
    *,
    entries: list[Entry],
    payee: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    at: datetime | None = None,
) -> Suggestion:
    """The best guess available, given whatever the caller already knows.

    Signals compose rather than compete: naming a payee narrows the pool that the place and
    time signals then rank, which is what makes filling one field improve the rest.
    """
    expenses = [entry for entry in entries if entry.kind is EntryKind.EXPENSE]
    if not expenses:
        return Suggestion(confidence=0, basis="none", reason="No spending recorded yet.")

    if payee and payee.strip():
        needle = payee.strip().casefold()
        matches = [entry for entry in expenses if entry.payee.casefold() == needle]
        if not matches:
            matches = [entry for entry in expenses if needle in entry.payee.casefold()]
        if matches:
            return _from(matches, basis="payee", detail=f"{len(matches)} past visits to this payee")

    if lat is not None and lon is not None:
        nearby = [
            entry
            for entry in expenses
            if entry.place
            and distance_metres(lat, lon, entry.place.lat, entry.place.lon) <= SAME_PLACE_METRES
        ]
        if nearby:
            # The payee you use most at this spot, then everything you spent there under it.
            common = Counter(entry.payee for entry in nearby).most_common(1)[0][0]
            here = [entry for entry in nearby if entry.payee == common]
            return _from(
                here,
                basis="place",
                detail=f"{len(here)} past purchases within {int(SAME_PLACE_METRES)}m",
            )

    if at is not None:
        slot = time_slot(at)
        same_slot = [
            entry for entry in expenses if slots_match(slot, time_slot(entry.at or entry.date))
        ]
        # Only worth offering once it is a pattern rather than a coincidence.
        if len(same_slot) >= 3:
            common = Counter(entry.payee for entry in same_slot).most_common(1)[0][0]
            usual = [entry for entry in same_slot if entry.payee == common]
            return _from(usual, basis="time", detail=f"{len(usual)} purchases in this time slot")

    return Suggestion(
        confidence=0, basis="none", reason="Nothing similar enough to go on yet.", sample_size=0
    )


def _from(matches: list[Entry], *, basis: str, detail: str) -> Suggestion:
    """Build a suggestion from a pool of comparable past entries."""
    matches = sorted(matches, key=lambda entry: entry.date, reverse=True)
    latest = matches[0]

    amounts = Counter(entry.amount for entry in matches)
    common_amount, seen = amounts.most_common(1)[0]
    repeats = seen > 1

    amount = common_amount if repeats else latest.amount
    source = matches[0] if not repeats else next(e for e in matches if e.amount == common_amount)

    buckets = Counter(share.bucket for entry in matches for share in entry.shares if share.bucket)
    bucket = buckets.most_common(1)[0][0] if buckets else None

    # Confidence is about how much agreement there is, not how many rows exist: five visits
    # that all cost the same is a better guess than fifty that never repeat.
    agreement = seen / len(matches)
    confidence = round(min(0.95, 0.35 + agreement * 0.5 + min(len(matches), 10) * 0.01), 2)

    reason = f"{detail}. " + (
        f"{seen} of them cost the same, so that amount is used."
        if repeats
        else "Every one differed, so the most recent is used."
    )

    return Suggestion(
        payee=latest.payee,
        amount=amount,
        bucket=bucket,
        shares=list(source.shares),
        items=list(source.items),
        place_name=latest.place.name if latest.place else None,
        confidence=confidence,
        basis=basis,
        reason=reason,
        sample_size=len(matches),
    )


def typical_basket(matches: list[Entry]) -> list[LineItem]:
    """The line items that show up on most receipts from a pool.

    Used for "the usual" at a place you always buy the same things at. A line has to appear on
    more than half the receipts to count, otherwise a one-off ends up in every suggestion.
    """
    with_items = [entry for entry in matches if entry.items]
    if len(with_items) < 2:
        return list(with_items[0].items) if with_items else []

    labels = Counter(item.label for entry in with_items for item in entry.items)
    threshold = len(with_items) / 2

    basket: list[LineItem] = []
    for label, count in labels.items():
        if count <= threshold:
            continue
        prices = Counter(
            item.amount for entry in with_items for item in entry.items if item.label == label
        )
        basket.append(LineItem(label=label, amount=prices.most_common(1)[0][0]))
    return basket


def shares_scaled_to(shares: list[Share], amount: Decimal) -> list[Share]:
    """Re-proportion a past split onto a different total, so a remembered 50/50 stays 50/50."""
    total = sum((share.amount for share in shares), start=ZERO)
    if total == ZERO or not shares:
        return []

    scaled: list[Share] = []
    running = ZERO
    for index, share in enumerate(shares):
        if index == len(shares) - 1:
            part = amount - running  # the last share absorbs the rounding
        else:
            part = (share.amount / total * amount).quantize(Decimal("0.01"))
            running += part
        scaled.append(share.model_copy(update={"amount": part}))
    return scaled


def to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
