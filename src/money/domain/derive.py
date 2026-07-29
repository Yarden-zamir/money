"""Everything derived from the ledger.

Nothing here is stored. Balances and envelope availability are folded from entries on every
read, so they cannot drift from history — which is exactly the property that makes the git
repo, rather than a database, the source of truth.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from itertools import accumulate

from pydantic import BaseModel

from money.domain.amounts import ZERO, quantize
from money.domain.models import Bucket, Entry, EntryKind


class Balance(BaseModel):
    person: str
    net: Decimal  # positive: the household owes them


class Settlement(BaseModel):
    """One suggested payment that reduces outstanding debt."""

    payer: str  # owes money
    payee: str  # is owed money
    amount: Decimal


class BucketState(BaseModel):
    bucket: str
    name: str
    group: str | None
    assigned: Decimal
    activity: Decimal  # negative for spending
    available: Decimal  # carryover + assigned + activity
    target: Decimal | None


class MonthView(BaseModel):
    person: str
    month: str
    ready_to_assign: Decimal
    income: Decimal
    assigned: Decimal
    buckets: list[BucketState]


def net_positions(entries: list[Entry], people: list[str]) -> list[Balance]:
    """Net position per person, folded over the whole ledger.

    Positive means the household owes them. People with no activity are still listed at zero,
    so a member never silently disappears from the balances screen.
    """
    borne: dict[str, Decimal] = defaultdict(lambda: ZERO)
    paid: dict[str, Decimal] = defaultdict(lambda: ZERO)

    for entry in entries:
        for share in entry.shares:
            borne[share.person] += share.amount
        for person, amount in entry.paid_by.items():
            paid[person] += amount

    return [Balance(person=p, net=quantize(borne[p] - paid[p])) for p in people]


def settle_up(balances: list[Balance]) -> list[Settlement]:
    """Suggest payments that clear the debts.

    Greedy: the largest debtor pays the largest creditor until one of them is square. This is
    not guaranteed minimal for every shape of debt, which is fine while budgets are a handful
    of people. Revisit if a budget ever exceeds ~8 members, where an extra hop is noticeable.
    """
    debtors = sorted([b for b in balances if b.net < ZERO], key=lambda b: b.net)
    creditors = sorted([b for b in balances if b.net > ZERO], key=lambda b: -b.net)

    owed = {b.person: -b.net for b in debtors}
    due = {b.person: b.net for b in creditors}
    payments: list[Settlement] = []

    for debtor in [b.person for b in debtors]:
        for creditor in [b.person for b in creditors]:
            if owed[debtor] == ZERO:
                break
            if due[creditor] == ZERO:
                continue
            amount = min(owed[debtor], due[creditor])
            payments.append(Settlement(payer=debtor, payee=creditor, amount=amount))
            owed[debtor] -= amount
            due[creditor] -= amount

    return payments


def months_between(start: str, end: str) -> list[str]:
    """Inclusive list of `YYYY-MM` from start to end. Empty if end precedes start."""
    start_year, start_month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    count = (end_year - start_year) * 12 + (end_month - start_month)
    if count < 0:
        return []
    return [
        f"{start_year + (start_month - 1 + offset) // 12:04d}-"
        f"{(start_month - 1 + offset) % 12 + 1:02d}"
        for offset in range(count + 1)
    ]


def _activity_by_month(entries: list[Entry], person: str) -> dict[tuple[str, str], Decimal]:
    """(month, bucket) -> summed activity for one person."""
    activity: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for entry in entries:
        for share in entry.shares:
            if share.person == person and share.bucket is not None:
                activity[(entry.month, share.bucket)] += share.amount
    return activity


def month_view(
    *,
    person: str,
    month: str,
    start_month: str,
    entries: list[Entry],
    buckets: list[Bucket],
    assignments: dict[str, dict[str, Decimal]],
) -> MonthView:
    """Envelope state for one person in one month.

    Availability carries over, so every month from `start_month` is folded rather than reading
    a stored opening balance that could drift. `assignments` is keyed by month, then bucket.
    """
    timeline = months_between(start_month, month)
    if not timeline:
        raise ValueError(f"month {month} precedes the budget start {start_month}")

    activity = _activity_by_month(entries, person)
    visible = [b for b in buckets if not b.archived]

    states: list[BucketState] = []
    for bucket in visible:
        # accumulate() folds carryover forward: each month's available is the previous
        # month's available plus what was assigned and spent this month.
        running = accumulate(
            (
                assignments.get(m, {}).get(bucket.id, ZERO) + activity.get((m, bucket.id), ZERO)
                for m in timeline
            ),
            initial=ZERO,
        )
        available = quantize(list(running)[-1])
        states.append(
            BucketState(
                bucket=bucket.id,
                name=bucket.name,
                group=bucket.group,
                assigned=quantize(assignments.get(month, {}).get(bucket.id, ZERO)),
                activity=quantize(activity.get((month, bucket.id), ZERO)),
                available=available,
                target=bucket.target.amount if bucket.target else None,
            )
        )

    income_to_date = quantize(
        sum(
            (
                share.amount
                for entry in entries
                if entry.kind is EntryKind.INCOME and entry.month in timeline
                for share in entry.shares
                if share.person == person
            ),
            start=ZERO,
        )
    )
    assigned_to_date = quantize(
        sum(
            (amount for m in timeline for amount in assignments.get(m, {}).values()),
            start=ZERO,
        )
    )

    return MonthView(
        person=person,
        month=month,
        ready_to_assign=quantize(income_to_date - assigned_to_date),
        income=quantize(
            sum(
                (
                    share.amount
                    for entry in entries
                    if entry.kind is EntryKind.INCOME and entry.month == month
                    for share in entry.shares
                    if share.person == person
                ),
                start=ZERO,
            )
        ),
        assigned=quantize(sum(assignments.get(month, {}).values(), start=ZERO)),
        buckets=states,
    )
