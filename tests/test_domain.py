"""Contract tests for the budget domain.

These assert behaviour that would break silently: money that stops adding up, a balance that
disagrees with history, an envelope that loses its carryover.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from money.domain.amounts import AmountError, allocate, parse_amount
from money.domain.derive import month_view, months_between, net_positions, settle_up
from money.domain.models import Bucket, Entry, EntryKind, Share, shares_from_split

D = Decimal


def entry(**overrides: object) -> Entry:
    base: dict[str, object] = {
        "id": "01K9VYQ2N3X8R4T7B0M6D5C1FA",
        "kind": "expense",
        "date": date(2026, 7, 14),
        "payee": "קפה גרג",
        "amount": "-50.00",
        "currency": "ILS",
        "paid_by": {"yarden": "-50.00"},
        "shares": [
            {"person": "yarden", "amount": "-25.00", "bucket": "fun-money"},
            {"person": "dana", "amount": "-25.00", "bucket": "fun-money"},
        ],
    }
    return Entry.model_validate(base | overrides)


class TestAmounts:
    def test_floats_are_rejected(self) -> None:
        with pytest.raises(AmountError, match="must not be floats"):
            parse_amount(50.1)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("total", "ratios"),
        [
            ("-50.00", {"a": D("0.5"), "b": D("0.5")}),
            ("-100.00", {"a": D("1")}),
            ("-0.01", {"a": D("0.5"), "b": D("0.5")}),
            ("-10.00", {"a": D("1") / 3, "b": D("1") / 3, "c": D("1") - 2 * (D("1") / 3)}),
        ],
    )
    def test_allocation_always_sums_to_the_total(self, total: str, ratios: dict) -> None:
        parts = allocate(D(total), ratios)
        assert sum(parts.values()) == D(total)

    def test_ratios_must_sum_to_one(self) -> None:
        with pytest.raises(AmountError, match="must sum to 1"):
            allocate(D("-50.00"), {"a": D("0.5"), "b": D("0.4")})


class TestEntry:
    def test_the_coffee_example_is_valid(self) -> None:
        """The worked example from specs/data-model.md must stay constructible."""
        e = entry()
        assert e.month == "2026-07"
        assert sum(s.amount for s in e.shares) == e.amount

    def test_shares_must_sum_to_the_entry_amount(self) -> None:
        with pytest.raises(ValidationError, match="shares sum to -40.00"):
            entry(
                shares=[
                    {"person": "yarden", "amount": "-25.00", "bucket": "fun-money"},
                    {"person": "dana", "amount": "-15.00", "bucket": "fun-money"},
                ]
            )

    def test_paid_by_must_sum_to_the_entry_amount(self) -> None:
        with pytest.raises(ValidationError, match="paid_by sums to -30.00"):
            entry(paid_by={"yarden": "-30.00"})

    def test_expense_shares_require_a_bucket(self) -> None:
        with pytest.raises(ValidationError, match="expense shares need a bucket"):
            entry(
                shares=[
                    {"person": "yarden", "amount": "-25.00", "bucket": "fun-money"},
                    {"person": "dana", "amount": "-25.00"},
                ]
            )

    def test_income_shares_must_not_have_a_bucket(self) -> None:
        with pytest.raises(ValidationError, match="must not have a bucket"):
            entry(
                kind="income",
                amount="5000.00",
                paid_by={"yarden": "5000.00"},
                shares=[{"person": "yarden", "amount": "5000.00", "bucket": "fun-money"}],
            )

    def test_a_person_can_split_their_own_share_across_buckets(self) -> None:
        e = entry(
            shares=[
                {"person": "yarden", "amount": "-20.00", "bucket": "fun-money"},
                {"person": "yarden", "amount": "-5.00", "bucket": "groceries"},
                {"person": "dana", "amount": "-25.00", "bucket": "fun-money"},
            ]
        )
        assert len([s for s in e.shares if s.person == "yarden"]) == 2


class TestBalances:
    def test_coffee_leaves_dana_owing_yarden(self) -> None:
        balances = net_positions([entry()], ["yarden", "dana"], "ILS")
        net = {b.person: b.net for b in balances}
        assert net == {"yarden": D("25.00"), "dana": D("-25.00")}

        payments = settle_up(balances, "ILS")
        assert len(payments) == 1
        assert (payments[0].payer, payments[0].payee) == ("dana", "yarden")
        assert payments[0].amount == D("25.00")

    def test_a_settlement_clears_the_debt(self) -> None:
        settlement = entry(
            id="01K9VYQ2N3X8R4T7B0M6D5C1FB",
            kind="settlement",
            date=date(2026, 7, 20),
            payee="settle up",
            amount="-25.00",
            paid_by={"dana": "-25.00"},
            shares=[{"person": "yarden", "amount": "-25.00"}],
        )
        balances = net_positions([entry(), settlement], ["yarden", "dana"], "ILS")
        assert all(b.net == D("0.00") for b in balances)
        assert settle_up(balances, "ILS") == []

    def test_members_with_no_activity_still_appear(self) -> None:
        balances = net_positions([entry()], ["yarden", "dana", "noa"], "ILS")
        assert {b.person for b in balances} == {"yarden", "dana", "noa"}


class TestMonthView:
    def test_carryover_folds_forward(self) -> None:
        buckets = [Bucket(id="fun-money", name="בילויים")]
        assignments = {"2026-07": {"fun-money": D("400.00")}, "2026-08": {"fun-money": D("400.00")}}
        view = month_view(
            person="yarden",
            month="2026-08",
            start_month="2026-07",
            entries=[entry()],  # -25.00 in July
            buckets=buckets,
            assignments={"yarden": assignments},
            people=["yarden"],
            currency="ILS",
        )
        fun = view.buckets[0]
        assert fun.assigned == D("400.00")  # August only
        assert fun.activity == D("0.00")  # nothing spent in August
        assert fun.available == D("775.00")  # 400 - 25 carried over, plus 400

    def test_ready_to_assign_is_income_minus_everything_assigned(self) -> None:
        income = entry(
            id="01K9VYQ2N3X8R4T7B0M6D5C1FC",
            kind="income",
            payee="salary",
            amount="5000.00",
            paid_by={"yarden": "5000.00"},
            shares=[{"person": "yarden", "amount": "5000.00"}],
        )
        view = month_view(
            person="yarden",
            month="2026-07",
            start_month="2026-07",
            entries=[income],
            buckets=[Bucket(id="fun-money", name="בילויים")],
            assignments={"yarden": {"2026-07": {"fun-money": D("400.00")}}},
            people=["yarden"],
            currency="ILS",
        )
        assert view.income == D("5000.00")
        assert view.ready_to_assign == D("4600.00")

    def test_month_before_budget_start_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="precedes the budget start"):
            month_view(
                person="yarden",
                month="2026-06",
                start_month="2026-07",
                entries=[],
                buckets=[],
                assignments={},
                people=["yarden"],
                currency="ILS",
            )

    def test_months_between_crosses_a_year(self) -> None:
        assert months_between("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]


class TestSplit:
    def test_shares_from_a_split_sum_exactly(self) -> None:
        shares = shares_from_split(
            {"yarden": D("0.5"), "dana": D("0.5")}, D("-284.51"), "groceries", EntryKind.EXPENSE
        )
        assert sum(s.amount for s in shares) == D("-284.51")
        assert {s.bucket for s in shares} == {"groceries"}

    def test_non_expense_kinds_drop_the_bucket(self) -> None:
        shares = shares_from_split(
            {"yarden": D("1")}, D("-100.00"), "groceries", EntryKind.SETTLEMENT
        )
        assert all(s.bucket is None for s in shares)

    def test_split_matches_the_worked_example(self) -> None:
        """50 shekel coffee, split evenly, both sides land in fun-money."""
        shares = shares_from_split(
            {"yarden": D("0.5"), "dana": D("0.5")}, D("-50.00"), "fun-money", EntryKind.EXPENSE
        )
        assert shares == [
            Share(person="yarden", amount=D("-25.00"), bucket="fun-money"),
            Share(person="dana", amount=D("-25.00"), bucket="fun-money"),
        ]


class TestCurrency:
    """A foreign entry is worth its converted amount, or nothing yet — never a guess."""

    def test_a_conversion_must_be_reproducible_from_amount_and_rate(self) -> None:
        with pytest.raises(ValidationError, match="fx amount is -100.00"):
            entry(
                currency="USD",
                fx={"rate": "3.7100", "amount": "-100.00", "at": "2026-07-14", "source": "table"},
            )

    def test_converted_shares_sum_exactly_to_the_converted_total(self) -> None:
        # 3.7 × -50 = -185.00; half each is -92.50, no drift. A rate that rounds badly:
        e = entry(
            currency="USD",
            fx={"rate": "3.3333", "amount": "-166.67", "at": "2026-07-14", "source": "table"},
        )
        shares = e.budget_shares("ILS")
        assert shares is not None
        assert sum(s.amount for s in shares) == D("-166.67")
        assert [s.person for s in shares] == ["yarden", "dana"]
        assert e.budget_paid_by("ILS") == {"yarden": D("-166.67")}

    def test_an_unconverted_entry_counts_in_its_own_column(self) -> None:
        dollars = entry(id="01K9VYQ2N3X8R4T7B0M6D5C1FB", currency="USD")
        balances = net_positions([entry(), dollars], ["yarden", "dana"], "ILS")
        by_person = {b.person: b for b in balances}

        assert by_person["yarden"].net == D("25.00")
        assert by_person["yarden"].foreign == {"USD": D("25.00")}
        assert by_person["dana"].foreign == {"USD": D("-25.00")}

        payments = settle_up(balances, "ILS")
        assert [(p.currency, p.amount) for p in payments] == [
            ("ILS", D("25.00")),
            ("USD", D("25.00")),
        ]

    def test_a_bucket_can_be_positive_in_one_currency_and_negative_in_another(self) -> None:
        dollars = entry(
            id="01K9VYQ2N3X8R4T7B0M6D5C1FB",
            currency="USD",
            amount="-10.00",
            paid_by={"yarden": "-10.00"},
            shares=[
                {"person": "yarden", "amount": "-5.00", "bucket": "fun-money"},
                {"person": "dana", "amount": "-5.00", "bucket": "fun-money"},
            ],
        )
        view = month_view(
            person="yarden",
            month="2026-07",
            start_month="2026-07",
            entries=[dollars],
            buckets=[Bucket(id="fun-money", name="Fun")],
            assignments={"yarden": {"2026-07": {"fun-money": D("100.00")}}},
            people=["yarden", "dana"],
            currency="ILS",
        )
        [fun] = view.buckets
        assert fun.available == D("100.00")  # the dollars never touch the shekel figure
        assert fun.activity == D("0.00")
        assert fun.foreign == {"USD": D("-10.00")}
        assert {f.person: f.foreign for f in fun.funders} == {
            "yarden": {"USD": D("-5.00")},
            "dana": {"USD": D("-5.00")},
        }

    def test_converted_spending_lands_in_the_shekel_column(self) -> None:
        dollars = entry(
            currency="USD",
            fx={"rate": "3.7000", "amount": "-185.00", "at": "2026-07-14", "source": "table"},
        )
        view = month_view(
            person="yarden",
            month="2026-07",
            start_month="2026-07",
            entries=[dollars],
            buckets=[Bucket(id="fun-money", name="Fun")],
            assignments={},
            people=["yarden", "dana"],
            currency="ILS",
        )
        [fun] = view.buckets
        assert fun.activity == D("-185.00")
        assert fun.foreign == {}

    def test_unconverted_income_is_not_ready_to_assign(self) -> None:
        salary = entry(
            kind="income",
            currency="USD",
            amount="1000.00",
            paid_by={"yarden": "1000.00"},
            shares=[{"person": "yarden", "amount": "1000.00"}],
        )
        view = month_view(
            person="yarden",
            month="2026-07",
            start_month="2026-07",
            entries=[salary],
            buckets=[],
            assignments={},
            people=["yarden"],
            currency="ILS",
        )
        assert view.ready_to_assign == D("0.00")
        assert view.foreign == {"USD": D("1000.00")}
