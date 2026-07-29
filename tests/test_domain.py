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
from money.domain.models import Bucket, Entry, EntryKind, Share
from money.domain.rules import Rule, first_match, shares_from_rule

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
        balances = net_positions([entry()], ["yarden", "dana"])
        net = {b.person: b.net for b in balances}
        assert net == {"yarden": D("25.00"), "dana": D("-25.00")}

        payments = settle_up(balances)
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
        balances = net_positions([entry(), settlement], ["yarden", "dana"])
        assert all(b.net == D("0.00") for b in balances)
        assert settle_up(balances) == []

    def test_members_with_no_activity_still_appear(self) -> None:
        balances = net_positions([entry()], ["yarden", "dana", "noa"])
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
            assignments=assignments,
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
            assignments={"2026-07": {"fun-money": D("400.00")}},
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
            )

    def test_months_between_crosses_a_year(self) -> None:
        assert months_between("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]


class TestRules:
    @pytest.fixture
    def ruleset(self) -> list[Rule]:
        return [
            Rule.model_validate(
                {"id": "hobby", "when": {"tag": "hobby"}, "split": {"yarden": 1.0}}
            ),
            Rule.model_validate(
                {
                    "id": "groceries",
                    "when": {"payee_contains": "שופרסל"},
                    "split": {"yarden": 0.5, "dana": 0.5},
                    "bucket": {"yarden": "groceries", "dana": "groceries"},
                }
            ),
            Rule.model_validate({"id": "split-5050", "split": {"yarden": 0.5, "dana": 0.5}}),
        ]

    def test_first_match_wins(self, ruleset: list[Rule]) -> None:
        matched = first_match(
            ruleset, payee="שופרסל דיל", tags=[], paid_by="yarden", amount=D("-284.50")
        )
        assert matched is not None
        assert matched.id == "groceries"

    def test_empty_when_is_the_catch_all(self, ruleset: list[Rule]) -> None:
        matched = first_match(ruleset, payee="קפה", tags=[], paid_by="dana", amount=D("-50.00"))
        assert matched is not None
        assert matched.id == "split-5050"

    def test_rule_produces_shares_that_sum_exactly(self, ruleset: list[Rule]) -> None:
        rule = first_match(ruleset, payee="שופרסל", tags=[], paid_by="yarden", amount=D("-284.51"))
        assert rule is not None
        shares = shares_from_rule(rule, D("-284.51"), EntryKind.EXPENSE)
        assert sum(s.amount for s in shares) == D("-284.51")
        assert {s.bucket for s in shares} == {"groceries"}

    def test_non_expense_kinds_drop_the_bucket(self, ruleset: list[Rule]) -> None:
        shares = shares_from_rule(ruleset[1], D("-100.00"), EntryKind.SETTLEMENT)
        assert all(s.bucket is None for s in shares)

    def test_split_ratios_must_sum_to_one(self) -> None:
        with pytest.raises(ValidationError, match="must sum to 1"):
            Rule.model_validate({"id": "bad", "split": {"yarden": 0.5, "dana": 0.2}})

    def test_bucket_map_cannot_name_someone_outside_the_split(self) -> None:
        with pytest.raises(ValidationError, match="names people not in the split"):
            Rule.model_validate(
                {"id": "bad", "split": {"yarden": 1.0}, "bucket": {"dana": "groceries"}}
            )

    def test_shares_from_rule_matches_the_worked_example(self) -> None:
        """50 shekel coffee, split evenly, both sides land in fun-money."""
        rule = Rule.model_validate(
            {
                "id": "coffee",
                "split": {"yarden": 0.5, "dana": 0.5},
                "bucket": {"yarden": "fun-money", "dana": "fun-money"},
            }
        )
        shares = shares_from_rule(rule, D("-50.00"), EntryKind.EXPENSE)
        assert shares == [
            Share(person="yarden", amount=D("-25.00"), bucket="fun-money"),
            Share(person="dana", amount=D("-25.00"), bucket="fun-money"),
        ]
