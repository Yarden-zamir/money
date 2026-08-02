"""Heuristic suggestions.

The failure modes are quiet: a confident guess drawn from one coincidence, a mean amount for
a shop where you never buy the same thing, or a split silently reproportioned wrong.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from money.domain.models import Entry, Share
from money.domain.suggest import (
    SAME_PLACE_METRES,
    distance_metres,
    shares_scaled_to,
    suggest,
    time_slot,
    typical_basket,
)

D = Decimal
CAFE = (32.0853, 34.7818)


def entry(
    ident: str,
    payee: str,
    amount: str,
    when: date,
    bucket: str = "eating-out",
    place: tuple[float, float] | None = None,
    items: list[dict] | None = None,
) -> Entry:
    return Entry.model_validate(
        {
            "id": ident,
            "kind": "expense",
            "date": when,
            "payee": payee,
            "amount": amount,
            "currency": "ILS",
            "paid_by": {"yarden": amount},
            "shares": [{"person": "yarden", "amount": amount, "bucket": bucket}],
            **({"place": {"lat": place[0], "lon": place[1]}} if place else {}),
            **({"items": items} if items else {}),
        }
    )


def ids(count: int) -> list[str]:
    return [f"01K9VYQ2N3X8R4T7B0M6D5C1{chr(65 + index)}A"[:26] for index in range(count)]


class TestDistance:
    def test_a_few_metres_apart_is_the_same_place(self) -> None:
        assert distance_metres(*CAFE, CAFE[0] + 0.0005, CAFE[1]) < SAME_PLACE_METRES

    def test_a_kilometre_away_is_not(self) -> None:
        assert distance_metres(*CAFE, CAFE[0] + 0.01, CAFE[1]) > SAME_PLACE_METRES


class TestPayeeSignal:
    def test_a_repeating_amount_is_used(self) -> None:
        entries = [
            entry(i, "קפה גרג", "-50.00", date(2026, 7, day))
            for i, day in zip(ids(3), (1, 8, 15), strict=True)
        ]
        result = suggest(entries=entries, payee="קפה גרג")

        assert result.basis == "payee"
        assert result.amount == D("-50.00")
        assert "cost the same" in result.reason
        assert result.bucket == "eating-out"

    def test_the_latest_is_used_when_every_visit_differs(self) -> None:
        """A mean is meaningless for a shop where you buy something different each time."""
        entries = [
            entry(ids(3)[0], "שופרסל", "-120.00", date(2026, 7, 1)),
            entry(ids(3)[1], "שופרסל", "-240.00", date(2026, 7, 8)),
            entry(ids(3)[2], "שופרסל", "-310.00", date(2026, 7, 15)),
        ]
        result = suggest(entries=entries, payee="שופרסל")

        assert result.amount == D("-310.00")
        assert "most recent" in result.reason

    def test_agreement_raises_confidence_above_disagreement(self) -> None:
        agreeing = [
            entry(i, "קפה", "-50.00", date(2026, 7, day))
            for i, day in zip(ids(4), (1, 8, 15, 22), strict=True)
        ]
        differing = [
            entry(i, "קפה", f"-{50 + index * 10}.00", date(2026, 7, 1 + index * 7))
            for index, i in enumerate(ids(4))
        ]
        assert (
            suggest(entries=agreeing, payee="קפה").confidence
            > suggest(entries=differing, payee="קפה").confidence
        )


class TestPlaceSignal:
    def test_being_at_the_same_spot_suggests_what_you_buy_there(self) -> None:
        entries = [
            entry(i, "קפה גרג", "-50.00", date(2026, 7, day), place=CAFE)
            for i, day in zip(ids(3), (1, 8, 15), strict=True)
        ]
        result = suggest(entries=entries, lat=CAFE[0], lon=CAFE[1])

        assert result.basis == "place"
        assert result.payee == "קפה גרג"
        assert result.amount == D("-50.00")

    def test_somewhere_else_gets_no_place_suggestion(self) -> None:
        entries = [entry(ids(1)[0], "קפה גרג", "-50.00", date(2026, 7, 1), place=CAFE)]
        result = suggest(entries=entries, lat=CAFE[0] + 0.05, lon=CAFE[1])
        assert result.basis == "none"

    def test_an_explicit_payee_outranks_the_place(self) -> None:
        """Naming the payee is the most specific thing the person can say."""
        entries = [
            entry(ids(2)[0], "קפה גרג", "-50.00", date(2026, 7, 1), place=CAFE),
            entry(ids(2)[1], "מאפייה", "-30.00", date(2026, 7, 2), place=CAFE),
        ]
        result = suggest(entries=entries, payee="מאפייה", lat=CAFE[0], lon=CAFE[1])
        assert result.basis == "payee"
        assert result.payee == "מאפייה"


class TestTimeSignal:
    def test_a_recurring_slot_is_suggested(self) -> None:
        # Four Saturday evenings.
        saturdays = [date(2026, 7, 4), date(2026, 7, 11), date(2026, 7, 18), date(2026, 7, 25)]
        entries = [
            entry(i, "אונליין", "-200.00", when, bucket="groceries")
            for i, when in zip(ids(4), saturdays, strict=True)
        ]
        result = suggest(entries=entries, at=datetime(2026, 8, 1, 12, 0))
        assert result.basis == "time"
        assert result.payee == "אונליין"

    def test_two_coincidences_are_not_a_pattern(self) -> None:
        entries = [
            entry(i, "אונליין", "-200.00", when)
            for i, when in zip(ids(2), (date(2026, 7, 4), date(2026, 7, 11)), strict=True)
        ]
        assert suggest(entries=entries, at=datetime(2026, 8, 1, 12, 0)).basis == "none"

    def test_slots_separate_days_of_the_week(self) -> None:
        assert time_slot(date(2026, 8, 1)) != time_slot(date(2026, 8, 2))

    def test_a_date_and_a_datetime_on_the_same_day_agree(self) -> None:
        """Entries carry a date and the query carries a clock time; they must still match."""
        assert time_slot(date(2026, 8, 1)) == time_slot(datetime(2026, 8, 1, 20, 30))


class TestBasket:
    def test_lines_on_most_receipts_form_the_usual(self) -> None:
        common = [{"label": "Coffee", "amount": "-15.00"}, {"label": "Cake", "amount": "-35.00"}]
        entries = [
            entry(ids(3)[0], "קפה גרג", "-50.00", date(2026, 7, 1), items=common),
            entry(ids(3)[1], "קפה גרג", "-50.00", date(2026, 7, 8), items=common),
            entry(
                ids(3)[2],
                "קפה גרג",
                "-65.00",
                date(2026, 7, 15),
                items=[*common, {"label": "Sandwich", "amount": "-15.00"}],
            ),
        ]
        basket = {item.label for item in typical_basket(entries)}
        assert basket == {"Coffee", "Cake"}  # the one-off sandwich is left out


class TestScaling:
    def test_a_remembered_split_keeps_its_proportions(self) -> None:
        half = [
            Share(person="yarden", amount=D("-25.00"), bucket="eating-out"),
            Share(person="dana", amount=D("-25.00"), bucket="eating-out"),
        ]
        scaled = shares_scaled_to(half, D("-80.00"))
        assert [share.amount for share in scaled] == [D("-40.00"), D("-40.00")]

    def test_scaling_always_sums_to_the_target(self) -> None:
        """The last share absorbs the rounding, so the entry can never fail to balance."""
        thirds = [
            Share(person="a", amount=D("-10.00"), bucket="x"),
            Share(person="b", amount=D("-10.00"), bucket="x"),
            Share(person="c", amount=D("-10.00"), bucket="x"),
        ]
        scaled = shares_scaled_to(thirds, D("-100.00"))
        assert sum(share.amount for share in scaled) == D("-100.00")
