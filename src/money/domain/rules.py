"""Categorisation rules.

A rule answers one question: "when I add this entry, which bucket does it belong in?" — so
the weekly groceries need no bucket typed in. Who *bears* it is not a rule's business; that
is the bucket's `split`, because it is a property of the category rather than of the payee.

Splitting the two is what lets a household fund a bucket unevenly without that funding
deciding whose expense it is. A rule that also carried a split had to be kept in step with
the bucket, and nothing made them agree.

First match wins, the same resolution order KitSHn uses for `.kitshn.yaml`, so the two
configs behave the same way for someone who edits both.

Rules apply **only** at creation time and only when the caller gives no explicit split.
Editing a rule never rewrites existing entries: history stays what actually happened.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from money.domain.amounts import allocate
from money.domain.models import BucketId, EntryKind, PersonId, Share


class Match(BaseModel):
    """An empty match matches everything, which is how a catch-all default is written."""

    model_config = ConfigDict(extra="forbid")

    payee_contains: str | None = None
    tag: str | None = None
    paid_by: PersonId | None = None
    min_amount: Decimal | None = None

    def matches(self, *, payee: str, tags: list[str], paid_by: str, amount: Decimal) -> bool:
        if self.payee_contains and self.payee_contains.casefold() not in payee.casefold():
            return False
        if self.tag and self.tag not in tags:
            return False
        if self.paid_by and self.paid_by != paid_by:
            return False
        # Compared on magnitude: expenses are negative, and a user writing min_amount: 100
        # means "entries of at least 100", not "entries above minus one hundred".
        return not (self.min_amount is not None and abs(amount) < abs(self.min_amount))


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    when: Match = Field(default_factory=Match)
    bucket: BucketId = Field(description="Which bucket a matching entry belongs in")


def first_match(
    rules: list[Rule], *, payee: str, tags: list[str], paid_by: str, amount: Decimal
) -> Rule | None:
    for rule in rules:
        if rule.when.matches(payee=payee, tags=tags, paid_by=paid_by, amount=amount):
            return rule
    return None


def shares_from_split(
    split: dict[str, Decimal], amount: Decimal, bucket: str | None, kind: EntryKind
) -> list[Share]:
    """Turn a bucket's split into shares that sum exactly to `amount`.

    `allocate` distributes the remainder rather than rounding each share independently, so
    three people splitting 10.00 get 3.34/3.33/3.33 and not a total of 9.99.

    Non-expense kinds carry no bucket, so it is dropped for them rather than producing an
    entry that fails validation.
    """
    parts = allocate(amount, split)
    return [
        Share(
            person=person,
            amount=part,
            bucket=bucket if kind is EntryKind.EXPENSE else None,
        )
        for person, part in parts.items()
        # A zero share is noise in the ledger; a person with a 0 share simply is not involved.
        if part != Decimal("0.00")
    ]
