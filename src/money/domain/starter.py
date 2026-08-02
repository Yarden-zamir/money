"""The buckets a person starts with.

A blank envelope budget is a worse starting point than a slightly wrong one. With no
buckets there is nothing to assign money to and nothing to file an expense under, so the
first entry fails before the person has learned what a bucket is — and "create a bucket"
is a poor first instruction when you do not yet know what the app calls things.

These are a starting point to rename and delete, not a taxonomy. Deliberately few: a long
list is as paralysing as an empty one, and the groups matter more than the individual
buckets because they are what the month screen subtotals by.

No targets are set. A target is a claim about what this person intends to spend, and
guessing that would put numbers on screen that nobody chose.
"""

from __future__ import annotations

from money.domain.models import Bucket

# Group names repeat across buckets on purpose: the month screen groups by this string.
STARTER_BUCKETS: list[Bucket] = [
    Bucket(id="rent", name="Rent", group="Bills", order=0),
    Bucket(id="utilities", name="Utilities", group="Bills", order=1),
    Bucket(id="groceries", name="Groceries", group="Everyday", order=0),
    Bucket(id="transport", name="Transport", group="Everyday", order=1),
    Bucket(id="eating-out", name="Eating out", group="Fun", order=0),
    Bucket(id="fun-money", name="Fun money", group="Fun", order=1),
    Bucket(id="savings", name="Savings", group="Goals", order=0),
]


def starter_buckets() -> list[Bucket]:
    """A fresh copy, so a caller mutating one person's buckets cannot alter the template."""
    return [bucket.model_copy(deep=True) for bucket in STARTER_BUCKETS]
