"""Budget domain models.

These mirror the on-disk YAML exactly. The file is the source of truth, so a model that
drifts from the layout in `specs/data-model.md` is a bug in this file, not in the data.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from money.domain.amounts import ZERO, format_amount, parse_amount
from money.domain.recurrence import Recurrence

PersonId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,38}$")]
BucketId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,38}$")]
Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class EntryKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    SETTLEMENT = "settlement"


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Share(Base):
    """One person's slice of an entry, booked against one of *their* buckets.

    A person may hold several shares in one entry when they split their own slice across
    buckets, so this is not keyed by person.
    """

    person: PersonId
    amount: Decimal
    bucket: BucketId | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _parse(cls, value: object) -> Decimal:
        return parse_amount(value)  # type: ignore[arg-type]


class LineItem(Base):
    """One line on a receipt.

    A receipt is one payment but several things bought, and they do not always belong in the
    same envelope or to the same person — a supermarket run is groceries and a bottle of wine.
    Splitting the *entry* cannot express that, because the entry's split is about the total.

    A line carries its own shares when it needs to. When it does not, it simply belongs to
    whatever the entry as a whole decided.
    """

    label: str = Field(min_length=1, max_length=200)
    amount: Decimal
    quantity: Decimal | None = None
    shares: list[Share] = Field(default_factory=list)

    @field_validator("amount", "quantity", mode="before")
    @classmethod
    def _parse(cls, value: object) -> Decimal | None:
        return None if value is None else parse_amount(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _shares_match_the_line(self) -> Self:
        if self.shares:
            total = sum((share.amount for share in self.shares), start=ZERO)
            if total != self.amount:
                raise ValueError(
                    f"line {self.label!r}: shares sum to {format_amount(total)}, "
                    f"line is {format_amount(self.amount)}"
                )
        return self


class Place(Base):
    """Where a payment happened.

    Coordinates are committed to the budget repo, which is a deliberate choice: it makes the
    suggestions work on every device and survive clearing a browser. It also means the repo
    holds a durable, shared record of where you have been — see specs/data-model.md.
    """

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = Field(default=None, max_length=200)
    # Whatever the places provider calls this venue, so a rename upstream does not fork it.
    provider_id: str | None = Field(default=None, max_length=200)


class Entry(Base):
    id: str = Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")  # ULID
    kind: EntryKind = EntryKind.EXPENSE

    # Two different questions, so two fields.
    #
    # `date` is an accounting decision: which day, and therefore which budget month, this
    # belongs to. A person may back-date it, and doing so must move the money, not lie about
    # when it happened.
    #
    # `at` is the wall-clock moment it actually occurred, recorded automatically. It is what
    # time-of-day patterns are read from — collapsing the two would mean a back-dated entry
    # silently claiming to have happened at midnight, which is where the weekday-only
    # limitation came from.
    #
    # Naive local time on purpose: which day a purchase belongs to is a local, human
    # judgement, and converting through a timezone would let a late-night purchase land in
    # the wrong budget month.
    date: date
    at: datetime | None = None
    payee: str = Field(min_length=1, max_length=200)
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    paid_by: dict[PersonId, Decimal]
    shares: list[Share] = Field(min_length=1)
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    rule: str | None = None
    items: list[LineItem] = Field(
        default_factory=list, description="Receipt lines; must sum to the entry amount"
    )
    place: Place | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> Decimal:
        return parse_amount(value)  # type: ignore[arg-type]

    @field_validator("paid_by", mode="before")
    @classmethod
    def _parse_paid_by(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {person: parse_amount(amount) for person, amount in value.items()}

    @model_validator(mode="after")
    def _check_balances(self) -> Self:
        """Both halves of the entry must add up to the entry total.

        This runs on read as well as write. A hand-edited ledger that does not balance is a
        loud error naming the entry, never a silently wrong total downstream.
        """
        if self.amount == ZERO:
            raise ValueError(f"entry {self.id}: amount must not be zero")

        paid = sum(self.paid_by.values(), start=ZERO)
        if paid != self.amount:
            raise ValueError(
                f"entry {self.id}: paid_by sums to {format_amount(paid)}, "
                f"entry amount is {format_amount(self.amount)}"
            )

        shared = sum((s.amount for s in self.shares), start=ZERO)
        if shared != self.amount:
            raise ValueError(
                f"entry {self.id}: shares sum to {format_amount(shared)}, "
                f"entry amount is {format_amount(self.amount)}"
            )

        # A receipt has to add up to what was paid, or the lines are describing a different
        # purchase from the one the ledger records.
        if self.items:
            lines = sum((item.amount for item in self.items), start=ZERO)
            if lines != self.amount:
                raise ValueError(
                    f"entry {self.id}: items sum to {format_amount(lines)}, "
                    f"entry amount is {format_amount(self.amount)}"
                )

            # When lines carry their own splits they become the detail behind the entry's
            # split, so the two must agree per person and bucket. Letting them drift would
            # give one number on the ledger and a different one on the receipt, and nothing
            # would say which was right.
            detailed = [item for item in self.items if item.shares]
            if detailed:
                if len(detailed) != len(self.items):
                    raise ValueError(
                        f"entry {self.id}: split some lines and not others — either every "
                        f"line carries a split or none do"
                    )
                if _by_person_and_bucket(
                    [share for item in self.items for share in item.shares]
                ) != _by_person_and_bucket(self.shares):
                    raise ValueError(
                        f"entry {self.id}: the line splits do not add up to the entry's split"
                    )

        if self.kind is EntryKind.EXPENSE:
            missing = [s.person for s in self.shares if s.bucket is None]
            if missing:
                raise ValueError(
                    f"entry {self.id}: expense shares need a bucket, missing for "
                    f"{', '.join(missing)}"
                )
        else:
            bucketed = [s.person for s in self.shares if s.bucket is not None]
            if bucketed:
                raise ValueError(
                    f"entry {self.id}: {self.kind} shares must not have a bucket, "
                    f"found for {', '.join(bucketed)}"
                )
        return self

    @property
    def month(self) -> str:
        return self.date.strftime("%Y-%m")


def _by_person_and_bucket(shares: list[Share]) -> dict[tuple[str, str | None], Decimal]:
    """Totals per (person, bucket), so two splits can be compared regardless of ordering."""
    totals: dict[tuple[str, str | None], Decimal] = {}
    for share in shares:
        key = (share.person, share.bucket)
        totals[key] = totals.get(key, ZERO) + share.amount
    return {key: value for key, value in totals.items() if value != ZERO}


class Target(Base):
    kind: str = Field(pattern=r"^(monthly|by_date|none)$")
    amount: Decimal | None = None
    due: date | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _parse(cls, value: object) -> Decimal | None:
        return None if value is None else parse_amount(value)  # type: ignore[arg-type]


class Bucket(Base):
    """One shared envelope. Several people fund it; anyone can spend against it.

    `split` and funding are deliberately independent. How much you put in this month is a
    cashflow decision; what proportion of this category's spending is *yours* is a fairness
    decision, and letting the first decide the second means you cannot fund a bucket generously
    one month without also taking on more of its cost.

    Keeping them apart is what allows an envelope to be in the red for one person and in the
    black for another: their position is what they funded minus what they bear.
    """

    id: BucketId
    name: str = Field(min_length=1, max_length=100)
    group: str | None = None
    target: Target | None = None
    archived: bool = False
    order: int = Field(
        default=0,
        description="Sort position within its group; ties fall back to name",
    )
    split: dict[PersonId, Decimal] = Field(
        default_factory=dict,
        description="Fraction of spending each person bears. Empty means split evenly.",
    )

    @field_validator("split", mode="before")
    @classmethod
    def _parse_split(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {person: Decimal(str(share)) for person, share in value.items()}

    @model_validator(mode="after")
    def _split_sums_to_one(self) -> Self:
        """An empty split means "evenly, among whoever is a member" and is resolved on read.

        A partial split is refused rather than normalised: shares that sum to 0.9 are a typo,
        and silently scaling them to 1 would attribute money in proportions nobody chose.
        """
        if not self.split:
            return self

        if any(share < 0 for share in self.split.values()):
            raise ValueError(f"bucket {self.id}: split shares cannot be negative")

        total = sum(self.split.values(), start=Decimal("0"))
        if abs(total - Decimal("1")) > Decimal("0.0001"):
            raise ValueError(f"bucket {self.id}: split sums to {total}, not 1")
        return self

    def split_for(self, members: list[str]) -> dict[str, Decimal]:
        """The effective split, filling in an even one when none is set.

        Resolved against the current members rather than stored, so adding someone to the
        budget does not leave every unconfigured bucket quietly attributing their spending to
        everyone else.
        """
        if self.split:
            return dict(self.split)
        if not members:
            return {}
        share = Decimal("1") / Decimal(len(members))
        return {person: share for person in members}


class Member(Base):
    person: PersonId
    name: str
    github: str | None = Field(
        default=None,
        description="Their GitHub login. A member without one is a placeholder, not an account.",
    )


class Scheduled(Base):
    """A template plus a recurrence: rent, a salary, a subscription.

    It holds the same two-sided split an entry does, so posting one produces an ordinary
    entry with nothing inferred at post time. `last_posted` is what stops the same charge
    being offered twice.
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    kind: EntryKind = EntryKind.EXPENSE
    payee: str = Field(min_length=1, max_length=200)
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    recurrence: Recurrence
    starts: date
    ends: date | None = None
    last_posted: date | None = None
    paused: bool = False

    paid_by: dict[PersonId, Decimal] = Field(default_factory=dict)
    shares: list[Share] = Field(default_factory=list)
    bucket: BucketId | None = Field(
        default=None, description="Where an expense lands when no explicit split is given"
    )
    note: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> Decimal:
        return parse_amount(value)  # type: ignore[arg-type]

    @field_validator("paid_by", mode="before")
    @classmethod
    def _parse_paid_by(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {person: parse_amount(amount) for person, amount in value.items()}

    @model_validator(mode="after")
    def _check_template(self) -> Self:
        if self.amount == ZERO:
            raise ValueError(f"scheduled {self.id}: amount must not be zero")
        if self.ends and self.ends < self.starts:
            raise ValueError(f"scheduled {self.id}: ends before it starts")

        # Shares are optional — an empty split means "decide by the rules when posting" — but
        # a split that is present must add up, exactly as it must on an entry.
        if self.shares:
            shared = sum((share.amount for share in self.shares), start=ZERO)
            if shared != self.amount:
                raise ValueError(
                    f"scheduled {self.id}: shares sum to {format_amount(shared)}, "
                    f"amount is {format_amount(self.amount)}"
                )
        if self.paid_by:
            paid = sum(self.paid_by.values(), start=ZERO)
            if paid != self.amount:
                raise ValueError(
                    f"scheduled {self.id}: paid_by sums to {format_amount(paid)}, "
                    f"amount is {format_amount(self.amount)}"
                )

        # An expense has to be able to name an envelope at post time, or posting would build
        # an entry the model rejects. Catching it here means the template is refused when it
        # is written, not weeks later when the charge falls due.
        if self.kind is EntryKind.EXPENSE and not self.shares and not self.bucket:
            raise ValueError(
                f"scheduled {self.id}: an expense needs a bucket, or an explicit split"
            )
        return self


class Budget(Base):
    """`budget.yaml` — identity and membership of one budget repo."""

    name: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    members: list[Member] = Field(min_length=1)
    start_month: Month

    @model_validator(mode="after")
    def _unique_people(self) -> Self:
        people = [m.person for m in self.members]
        duplicates = {p for p in people if people.count(p) > 1}
        if duplicates:
            raise ValueError(
                f"duplicate person ids in budget.yaml: {', '.join(sorted(duplicates))}"
            )
        return self

    def person_for_github(self, login: str) -> str | None:
        """Map a GitHub login onto a person id. Case-insensitive: GitHub logins are."""
        folded = login.casefold()
        for member in self.members:
            if member.github and member.github.casefold() == folded:
                return member.person
        return None
