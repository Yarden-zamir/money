"""Everything derived from the ledger.

Nothing here is stored. Balances and envelope availability are folded from entries on every
read, so they cannot drift from history — which is exactly the property that makes the git
repo, rather than a database, the source of truth.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from itertools import accumulate

from pydantic import BaseModel, Field

from money.domain.amounts import ZERO, quantize
from money.domain.models import Bucket, Entry, EntryKind

# Whatever is not yet in the budget currency, per currency. Never added to the budget figure
# and never to each other: five unconverted dollars are five dollars, not "about eighteen
# shekels". See specs/currency.md.
Foreign = dict[str, Decimal]


class Balance(BaseModel):
    person: str
    net: Decimal  # positive: the household owes them
    foreign: Foreign = Field(
        default_factory=dict, description="Net position per unconverted currency"
    )


class Settlement(BaseModel):
    """One suggested payment that reduces outstanding debt, in one currency."""

    payer: str  # owes money
    payee: str  # is owed money
    amount: Decimal
    currency: str


class FunderState(BaseModel):
    """One person's standing in one shared bucket.

    `available` can be negative while another funder's is positive — that is the point of
    separating funding from split. It means this person is consuming more of the category than
    they have put in, which is fixed by funding more or by changing the split, and is a
    different problem from owing somebody cash.
    """

    person: str
    split: Decimal = Field(description="Fraction of this bucket's spending they bear")
    assigned: Decimal = Field(description="What they put in this month")
    activity: Decimal = Field(description="What they bore this month; negative for spending")
    available: Decimal = Field(description="Their carried position: funded minus borne")
    foreign: Foreign = Field(
        default_factory=dict,
        description="What they bore here in currencies not yet converted, carried to date",
    )


class BucketState(BaseModel):
    """A shared bucket, totalled for the household and broken down per funder."""

    bucket: str
    name: str
    group: str | None
    assigned: Decimal  # household total for this month
    activity: Decimal  # household total for this month; negative for spending
    available: Decimal  # household carryover + assigned + activity
    target: Decimal | None
    funders: list[FunderState] = Field(default_factory=list)
    foreign: Foreign = Field(
        default_factory=dict,
        description="Spent against this bucket in currencies not yet converted, to date",
    )


class MonthView(BaseModel):
    person: str
    month: str
    ready_to_assign: Decimal
    income: Decimal
    assigned: Decimal
    buckets: list[BucketState]
    foreign: Foreign = Field(
        default_factory=dict,
        description="This person's income not yet converted, so not yet assignable",
    )


def _prune(foreign: dict[str, Decimal]) -> Foreign:
    """Zero is absence: a currency that netted out is not worth a chip on screen."""
    return {code: quantize(amount) for code, amount in sorted(foreign.items()) if amount != ZERO}


def net_positions(entries: list[Entry], people: list[str], currency: str) -> list[Balance]:
    """Net position per person, folded over the whole ledger.

    Positive means the household owes them. People with no activity are still listed at zero,
    so a member never silently disappears from the balances screen.

    Converted entries count in the budget currency through their derived shares; unconverted
    ones count in their own, in `foreign`, and the two are never added.
    """
    borne: dict[str, Decimal] = defaultdict(lambda: ZERO)
    paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
    foreign: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))

    for entry in entries:
        code = entry.foreign(currency)
        if code is None:
            for share in entry.budget_shares(currency) or []:
                borne[share.person] += share.amount
            for person, amount in (entry.budget_paid_by(currency) or {}).items():
                paid[person] += amount
        else:
            for share in entry.shares:
                foreign[share.person][code] += share.amount
            for person, amount in entry.paid_by.items():
                foreign[person][code] -= amount

    return [
        Balance(person=p, net=quantize(borne[p] - paid[p]), foreign=_prune(foreign[p]))
        for p in people
    ]


def settle_up(balances: list[Balance], currency: str) -> list[Settlement]:
    """Suggest payments that clear the debts, one set per currency.

    Greedy: the largest debtor pays the largest creditor until one of them is square. This is
    not guaranteed minimal for every shape of debt, which is fine while budgets are a handful
    of people. Revisit if a budget ever exceeds ~8 members, where an extra hop is noticeable.

    Currencies never mix: a dollar debt is settled in dollars, or converted first.
    """
    payments = _settle(currency, {b.person: b.net for b in balances})
    codes = sorted({code for b in balances for code in b.foreign})
    for code in codes:
        payments += _settle(code, {b.person: b.foreign.get(code, ZERO) for b in balances})
    return payments


def _settle(currency: str, nets: dict[str, Decimal]) -> list[Settlement]:
    debtors = sorted([p for p, net in nets.items() if net < ZERO], key=lambda p: nets[p])
    creditors = sorted([p for p, net in nets.items() if net > ZERO], key=lambda p: -nets[p])

    owed = {p: -nets[p] for p in debtors}
    due = {p: nets[p] for p in creditors}
    payments: list[Settlement] = []

    for debtor in debtors:
        for creditor in creditors:
            if owed[debtor] == ZERO:
                break
            if due[creditor] == ZERO:
                continue
            amount = min(owed[debtor], due[creditor])
            payments.append(
                Settlement(payer=debtor, payee=creditor, amount=amount, currency=currency)
            )
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


def shift_month(month: str, delta: int) -> str:
    """`2026-01` shifted by -1 is `2025-12`."""
    year, number = (int(part) for part in month.split("-"))
    total = year * 12 + (number - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _activity_by_month(
    entries: list[Entry], person: str, currency: str
) -> dict[tuple[str, str], Decimal]:
    """(month, bucket) -> summed activity for one person, in the budget currency."""
    activity: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for entry in entries:
        for share in entry.budget_shares(currency) or []:
            if share.person == person and share.bucket is not None:
                activity[(entry.month, share.bucket)] += share.amount
    return activity


def _foreign_by_bucket(
    entries: list[Entry], person: str, currency: str, through: list[str]
) -> dict[str, dict[str, Decimal]]:
    """bucket -> currency -> what this person bore there, unconverted, up to `through`."""
    foreign: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    months = set(through)
    for entry in entries:
        code = entry.foreign(currency)
        if code is None or entry.month not in months:
            continue
        for share in entry.shares:
            if share.person == person and share.bucket is not None:
                foreign[share.bucket][code] += share.amount
    return foreign


def month_view(
    *,
    person: str,
    month: str,
    start_month: str,
    entries: list[Entry],
    buckets: list[Bucket],
    assignments: dict[str, dict[str, dict[str, Decimal]]],
    people: list[str],
    currency: str,
) -> MonthView:
    """Envelope state for one month, per funder as well as for the household.

    Availability carries over, so every month from `start_month` is folded rather than reading
    a stored opening balance that could drift. `assignments` is keyed by person, then month,
    then bucket.

    `person` names whose ready-to-assign this is — that figure is genuinely personal, because
    income arrives to a person. The buckets themselves are shared, and each carries what every
    funder put in and bears.
    """
    timeline = months_between(start_month, month)
    if not timeline:
        raise ValueError(f"month {month} precedes the budget start {start_month}")

    borne = {who: _activity_by_month(entries, who, currency) for who in people}
    unconverted = {who: _foreign_by_bucket(entries, who, currency, timeline) for who in people}
    visible = [b for b in buckets if not b.archived]

    states: list[BucketState] = []
    for bucket in visible:
        split = bucket.split_for(people)
        funders: list[FunderState] = []

        for who in people:
            mine = assignments.get(who, {})
            # accumulate() folds carryover forward: each month's available is the previous
            # month's available plus what that person assigned and bore this month.
            running = accumulate(
                (
                    mine.get(m, {}).get(bucket.id, ZERO) + borne[who].get((m, bucket.id), ZERO)
                    for m in timeline
                ),
                initial=ZERO,
            )
            funders.append(
                FunderState(
                    person=who,
                    split=split.get(who, ZERO),
                    assigned=quantize(mine.get(month, {}).get(bucket.id, ZERO)),
                    activity=quantize(borne[who].get((month, bucket.id), ZERO)),
                    available=quantize(list(running)[-1]),
                    foreign=_prune(unconverted[who].get(bucket.id, {})),
                )
            )

        household_foreign: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for funder in funders:
            for code, amount in funder.foreign.items():
                household_foreign[code] += amount

        states.append(
            BucketState(
                bucket=bucket.id,
                name=bucket.name,
                group=bucket.group,
                assigned=quantize(sum((f.assigned for f in funders), start=ZERO)),
                activity=quantize(sum((f.activity for f in funders), start=ZERO)),
                available=quantize(sum((f.available for f in funders), start=ZERO)),
                target=bucket.target.amount if bucket.target else None,
                funders=funders,
                foreign=_prune(household_foreign),
            )
        )

    income_to_date = quantize(
        sum(
            (
                share.amount
                for entry in entries
                if entry.kind is EntryKind.INCOME and entry.month in timeline
                for share in entry.budget_shares(currency) or []
                if share.person == person
            ),
            start=ZERO,
        )
    )
    # Foreign income that has not been converted cannot fund an envelope yet — assignments
    # are in the budget currency — so it is reported beside ready-to-assign, not inside it.
    foreign_income: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for entry in entries:
        code = entry.foreign(currency)
        if code is None or entry.kind is not EntryKind.INCOME or entry.month not in timeline:
            continue
        for share in entry.shares:
            if share.person == person:
                foreign_income[code] += share.amount
    ours = assignments.get(person, {})
    assigned_to_date = quantize(
        sum(
            (amount for m in timeline for amount in ours.get(m, {}).values()),
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
                    for share in entry.budget_shares(currency) or []
                    if share.person == person
                ),
                start=ZERO,
            )
        ),
        assigned=quantize(sum(ours.get(month, {}).values(), start=ZERO)),
        buckets=states,
        foreign=_prune(foreign_income),
    )
