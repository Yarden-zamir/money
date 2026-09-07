"""The exchange-rate provider, against a saved feed: no network in the suite."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from money.api.rates import rate_from_feed

FEED = (Path(__file__).parent / "fixtures" / "ecb-sample.xml").read_text(encoding="utf-8")


def test_a_cross_rate_goes_through_the_euro() -> None:
    # 4.0440 shekels per euro / 1.0900 dollars per euro = 3.7101 shekels per dollar.
    assert rate_from_feed(FEED, "USD", "ILS", date(2026, 7, 14)) == Decimal("3.7101")


def test_the_euro_itself_needs_no_cross() -> None:
    assert rate_from_feed(FEED, "EUR", "ILS", date(2026, 7, 14)) == Decimal("4.0440")
    assert rate_from_feed(FEED, "ILS", "EUR", date(2026, 7, 14)) == Decimal("0.2473")


def test_a_weekend_takes_the_last_published_day() -> None:
    # 2026-07-12 is a Sunday; the feed's last day before it is the 10th.
    assert rate_from_feed(FEED, "USD", "ILS", date(2026, 7, 12)) == Decimal("3.7000")


def test_a_day_before_the_feed_starts_has_no_answer() -> None:
    assert rate_from_feed(FEED, "USD", "ILS", date(2026, 7, 1)) is None


def test_an_unquoted_currency_has_no_answer() -> None:
    assert rate_from_feed(FEED, "XYZ", "ILS", date(2026, 7, 14)) is None
