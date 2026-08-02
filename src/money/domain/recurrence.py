"""Recurring entries.

A recurrence describes *when* something repeats. It never creates an entry on its own: money
appears in the ledger only when a person posts it, so every commit still has an author and
nothing is written into a budget while nobody is looking. What this module produces is a list
of dates that are due; posting them is an explicit action.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Cadence(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class Recurrence(BaseModel):
    """How often something repeats.

    Three cadences cover what a household actually has: a salary and rent monthly, a cleaner
    weekly, insurance yearly. More exotic rules can be added when something real needs one.
    """

    model_config = ConfigDict(extra="forbid")

    cadence: Cadence
    day: Annotated[int, Field(ge=1, le=31)] | None = Field(
        default=None, description="Day of the month, for monthly and yearly"
    )
    weekday: Annotated[int, Field(ge=0, le=6)] | None = Field(
        default=None, description="Monday is 0, for weekly"
    )
    month: Annotated[int, Field(ge=1, le=12)] | None = Field(
        default=None, description="Month, for yearly"
    )
    interval: Annotated[int, Field(ge=1, le=12)] = Field(
        default=1, description="Every N periods; 2 with a monthly cadence is every other month"
    )

    @model_validator(mode="after")
    def _needs_the_right_fields(self) -> Self:
        if self.cadence is Cadence.WEEKLY and self.weekday is None:
            raise ValueError("a weekly recurrence needs a weekday")
        if self.cadence in (Cadence.MONTHLY, Cadence.YEARLY) and self.day is None:
            raise ValueError(f"a {self.cadence} recurrence needs a day of the month")
        if self.cadence is Cadence.YEARLY and self.month is None:
            raise ValueError("a yearly recurrence needs a month")
        return self

    def describe(self) -> str:
        """A short, translatable-free summary for logs and commit messages."""
        every = "" if self.interval == 1 else f"every {self.interval} "
        if self.cadence is Cadence.WEEKLY:
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return f"{every}weekly on {names[self.weekday or 0]}"
        if self.cadence is Cadence.MONTHLY:
            return f"{every}monthly on day {self.day}"
        return f"{every}yearly on {self.month:02d}-{self.day:02d}"


def _clamp_to_month(year: int, month: int, day: int) -> date:
    """Day 31 in a 30-day month means the last day, not a skipped month.

    Rent due on the 31st still falls due in February. Rolling into March instead would move
    the charge into the wrong budget month, which is worse than being a day or two early.
    """
    return date(year, month, min(day, monthrange(year, month)[1]))


def _add_months(anchor: date, months: int) -> tuple[int, int]:
    total = (anchor.year * 12 + anchor.month - 1) + months
    return total // 12, total % 12 + 1


def occurrences(
    recurrence: Recurrence, *, start: date, through: date, after: date | None = None
) -> list[date]:
    """Every date this recurrence falls due in `[start, through]`.

    `after` excludes anything already posted, so asking twice does not offer the same charge
    twice. The window is bounded by `through`, so a recurrence with no end date cannot produce
    an unbounded list.
    """
    if through < start:
        return []

    floor = max(start, (after + timedelta(days=1)) if after else start)
    dates: list[date] = []

    if recurrence.cadence is Cadence.WEEKLY:
        step = 7 * recurrence.interval
        # First occurrence on or after `start` that falls on the right weekday.
        offset = (recurrence.weekday or 0) - start.weekday()
        current = start + timedelta(days=offset % 7)
        while current <= through:
            if current >= floor:
                dates.append(current)
            current += timedelta(days=step)
        return dates

    if recurrence.cadence is Cadence.MONTHLY:
        year, month = start.year, start.month
        while True:
            candidate = _clamp_to_month(year, month, recurrence.day or 1)
            if candidate > through:
                break
            if candidate >= floor and candidate >= start:
                dates.append(candidate)
            year, month = _add_months(date(year, month, 1), recurrence.interval)
        return dates

    year = start.year
    while True:
        candidate = _clamp_to_month(year, recurrence.month or 1, recurrence.day or 1)
        if candidate > through:
            break
        if candidate >= floor and candidate >= start:
            dates.append(candidate)
        year += recurrence.interval
    return dates
