"""Recurrence maths.

The failure modes here are quiet ones: a charge that lands in the wrong budget month, one
that gets posted twice, or one that disappears in February.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from money.domain.recurrence import Cadence, Recurrence, occurrences


def monthly(day: int, interval: int = 1) -> Recurrence:
    return Recurrence(cadence=Cadence.MONTHLY, day=day, interval=interval)


class TestMonthly:
    def test_a_short_month_clamps_instead_of_skipping(self) -> None:
        """Rent due on the 31st is still due in February.

        Rolling forward to March would move the charge into the wrong budget month, which is
        worse than being a day early.
        """
        dates = occurrences(monthly(31), start=date(2026, 1, 1), through=date(2026, 4, 30))
        assert dates == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 30),
        ]

    def test_a_leap_february_uses_the_29th(self) -> None:
        dates = occurrences(monthly(30), start=date(2028, 2, 1), through=date(2028, 2, 29))
        assert dates == [date(2028, 2, 29)]

    def test_an_interval_skips_months(self) -> None:
        dates = occurrences(
            monthly(1, interval=3), start=date(2026, 1, 1), through=date(2026, 12, 31)
        )
        assert dates == [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)]

    def test_nothing_before_the_start(self) -> None:
        dates = occurrences(monthly(1), start=date(2026, 3, 15), through=date(2026, 5, 31))
        assert dates == [date(2026, 4, 1), date(2026, 5, 1)]


class TestWeekly:
    def test_it_lands_on_the_right_weekday(self) -> None:
        dates = occurrences(
            Recurrence(cadence=Cadence.WEEKLY, weekday=0),  # Monday
            start=date(2026, 1, 1),
            through=date(2026, 1, 31),
        )
        assert dates == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)]
        assert all(when.weekday() == 0 for when in dates)

    def test_a_fortnightly_interval(self) -> None:
        dates = occurrences(
            Recurrence(cadence=Cadence.WEEKLY, weekday=4, interval=2),
            start=date(2026, 1, 1),
            through=date(2026, 2, 28),
        )
        assert all(
            (later - earlier).days == 14 for earlier, later in zip(dates, dates[1:], strict=False)
        )


class TestYearly:
    def test_it_repeats_once_a_year(self) -> None:
        dates = occurrences(
            Recurrence(cadence=Cadence.YEARLY, month=3, day=1),
            start=date(2026, 1, 1),
            through=date(2028, 12, 31),
        )
        assert dates == [date(2026, 3, 1), date(2027, 3, 1), date(2028, 3, 1)]


class TestAlreadyPosted:
    def test_posted_dates_are_not_offered_again(self) -> None:
        """Opening the due list twice must not offer the same charge twice."""
        every = monthly(1)
        first = occurrences(every, start=date(2026, 1, 1), through=date(2026, 4, 30))
        assert len(first) == 4

        after = occurrences(
            every, start=date(2026, 1, 1), through=date(2026, 4, 30), after=date(2026, 2, 1)
        )
        assert after == [date(2026, 3, 1), date(2026, 4, 1)]

    def test_the_horizon_bounds_an_endless_recurrence(self) -> None:
        """A recurrence with no end date must not produce an unbounded list."""
        dates = occurrences(monthly(1), start=date(2020, 1, 1), through=date(2020, 12, 31))
        assert len(dates) == 12

    def test_a_window_that_ends_before_it_starts_is_empty(self) -> None:
        assert occurrences(monthly(1), start=date(2026, 5, 1), through=date(2026, 4, 1)) == []


class TestValidation:
    def test_a_weekly_recurrence_needs_a_weekday(self) -> None:
        with pytest.raises(ValidationError, match="needs a weekday"):
            Recurrence(cadence=Cadence.WEEKLY)

    def test_a_monthly_recurrence_needs_a_day(self) -> None:
        with pytest.raises(ValidationError, match="needs a day of the month"):
            Recurrence(cadence=Cadence.MONTHLY)

    def test_a_yearly_recurrence_needs_a_month(self) -> None:
        with pytest.raises(ValidationError, match="needs a month"):
            Recurrence(cadence=Cadence.YEARLY, day=1)


class TestScheduledTemplate:
    def test_an_expense_needs_somewhere_to_land(self) -> None:
        """Caught when the template is written, not weeks later when the charge falls due."""
        from money.domain.models import Scheduled

        with pytest.raises(ValidationError, match="needs a bucket, or an explicit split"):
            Scheduled(
                id="rent",
                name="Rent",
                payee="Landlord",
                amount="-5200.00",
                currency="ILS",
                recurrence=monthly(1),
                starts=date(2026, 1, 1),
            )

    def test_a_split_that_does_not_add_up_is_refused(self) -> None:
        from money.domain.models import Scheduled

        with pytest.raises(ValidationError, match="shares sum to"):
            Scheduled(
                id="rent",
                name="Rent",
                payee="Landlord",
                amount="-5200.00",
                currency="ILS",
                recurrence=monthly(1),
                starts=date(2026, 1, 1),
                shares=[{"person": "yarden", "amount": "-2000.00", "bucket": "rent"}],
            )

    def test_it_cannot_end_before_it_starts(self) -> None:
        from money.domain.models import Scheduled

        with pytest.raises(ValidationError, match="ends before it starts"):
            Scheduled(
                id="rent",
                name="Rent",
                payee="Landlord",
                amount="-5200.00",
                currency="ILS",
                bucket="rent",
                recurrence=monthly(1),
                starts=date(2026, 6, 1),
                ends=date(2026, 1, 1),
            )
