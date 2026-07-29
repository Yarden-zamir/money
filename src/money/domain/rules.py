"""Default split rules.

Rules answer "when I add this entry, who bears it and out of which bucket?" so the common
case — a shared coffee, the weekly groceries — is one line of input instead of a full split.

First match wins, the same resolution order KitSHn uses for `.kitshn.yaml`, so the two
configs behave the same way for someone who edits both.

Rules apply **only** at creation time and only when the caller gives no explicit split. Editing
a rule never rewrites existing entries: history stays what actually happened.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from money.domain.amounts import allocate
from money.domain.models import BucketId, EntryKind, PersonId, Share

Ratio = Annotated[Decimal, Field(ge=0, le=1)]


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
    split: dict[PersonId, Ratio]
    bucket: dict[PersonId, BucketId] = Field(default_factory=dict)

    @field_validator("split", mode="before")
    @classmethod
    def _decimalize(cls, value: object) -> object:
        """YAML parses `0.5` as a float, so ratios arrive as floats and must be converted.

        Going through `str` is exact for the short literals a human writes. Amounts get no
        such tolerance — see `amounts.parse_amount`, which rejects floats outright — because
        a ratio is a rounding input while an amount is the money itself.
        """
        if not isinstance(value, dict):
            return value
        return {person: Decimal(str(ratio)) for person, ratio in value.items()}

    @model_validator(mode="after")
    def _ratios_sum_to_one(self) -> Self:
        if not self.split:
            raise ValueError(f"rule {self.id}: split must name at least one person")
        total = sum(self.split.values(), start=Decimal(0))
        if total != Decimal(1):
            raise ValueError(f"rule {self.id}: split ratios sum to {total}, must sum to 1")
        unknown = set(self.bucket) - set(self.split)
        if unknown:
            raise ValueError(
                f"rule {self.id}: bucket names people not in the split: {', '.join(sorted(unknown))}"
            )
        return self


def first_match(
    rules: list[Rule], *, payee: str, tags: list[str], paid_by: str, amount: Decimal
) -> Rule | None:
    for rule in rules:
        if rule.when.matches(payee=payee, tags=tags, paid_by=paid_by, amount=amount):
            return rule
    return None


def shares_from_rule(rule: Rule, amount: Decimal, kind: EntryKind) -> list[Share]:
    """Turn a matched rule into shares that sum exactly to `amount`.

    Non-expense kinds carry no bucket, so a rule's bucket map is ignored for them rather than
    producing an entry that fails validation.
    """
    parts = allocate(amount, rule.split)
    return [
        Share(
            person=person,
            amount=part,
            bucket=rule.bucket.get(person) if kind is EntryKind.EXPENSE else None,
        )
        for person, part in parts.items()
        # A zero share is noise in the ledger; a person with a 0 ratio simply is not involved.
        if part != Decimal("0.00")
    ]
