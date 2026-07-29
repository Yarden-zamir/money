"""Budget domain models.

These mirror the on-disk YAML exactly. The file is the source of truth, so a model that
drifts from the layout in `specs/data-model.md` is a bug in this file, not in the data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from money.domain.amounts import ZERO, format_amount, parse_amount

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


class Entry(Base):
    id: str = Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")  # ULID
    kind: EntryKind = EntryKind.EXPENSE
    date: date
    payee: str = Field(min_length=1, max_length=200)
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    paid_by: dict[PersonId, Decimal]
    shares: list[Share] = Field(min_length=1)
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    rule: str | None = None

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


class Target(Base):
    kind: str = Field(pattern=r"^(monthly|by_date|none)$")
    amount: Decimal | None = None
    due: date | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _parse(cls, value: object) -> Decimal | None:
        return None if value is None else parse_amount(value)  # type: ignore[arg-type]


class Bucket(Base):
    id: BucketId
    name: str = Field(min_length=1, max_length=100)
    group: str | None = None
    target: Target | None = None
    archived: bool = False


class Member(Base):
    person: PersonId
    name: str
    github: str | None = None


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
