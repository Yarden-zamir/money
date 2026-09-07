"""API tests against a real git-backed store.

GitHub is the only thing faked here: the budget context is overridden to point at a local
bare repo. Everything below it — rules, splits, commits, balances — is the real code path.
"""

from __future__ import annotations

import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from money.api.app import create_app
from money.api.deps import BudgetContext, _acting_as, budget_context, writable
from money.api.errors import ApiError
from money.store.gitrepo import GitRepo
from money.store.store import Actor, BudgetStore, new_id

D = Decimal

BUDGET_YAML = """\
name: joint
currency: ILS
start_month: 2026-07
members:
  - person: yarden
    name: Yarden
    github: dev
  - person: dana
    name: Dana
    github: dana-example
"""

RULES_YAML = """\
- id: groceries
  when: {payee_contains: שופרסל}
  bucket: groceries
- id: split-5050
  when: {}
  bucket: fun-money
"""

# Buckets are shared and carry the split that decides who bears their spending.
BUCKETS_YAML = """\
- id: fun-money
  name: בילויים
  split: {yarden: 0.5, dana: 0.5}
- id: groceries
  name: מכולת
  split: {yarden: 0.5, dana: 0.5}
"""


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "var"))

    from money.api.config import settings

    settings.cache_clear()

    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True
    )
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True)
    (seed / "budget.yaml").write_text(BUDGET_YAML, encoding="utf-8")
    (seed / "rules.yaml").write_text(RULES_YAML, encoding="utf-8")
    (seed / "buckets.yaml").write_text(BUCKETS_YAML, encoding="utf-8")
    for args in (
        ["config", "user.email", "seed@example.com"],
        ["config", "user.name", "seed"],
        ["add", "-A"],
        ["commit", "-m", "chore: seed"],
        ["push", "origin", "main"],
    ):
        subprocess.run(["git", *args], cwd=seed, check=True, capture_output=True)

    repo = GitRepo(path=tmp_path / "clone", remote=str(bare), branch="main")
    repo.ensure_clone("")
    context = BudgetContext(
        slug="joint",
        repo="Yarden-zamir/budget-joint",
        store=BudgetStore(repo),
        actor=Actor(login="dev", name="Dev User", email="dev@localhost", token=""),
        can_write=True,
    )

    app = create_app()
    app.dependency_overrides[budget_context] = lambda: context
    app.dependency_overrides[writable] = lambda: context
    with TestClient(app) as test_client:
        yield test_client

    settings.cache_clear()


def post_entry(client: TestClient, **body: object) -> dict:
    response = client.post("/api/v1/budgets/joint/entries", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestEntries:
    def test_rules_split_an_entry_and_record_which_rule_did_it(self, client: TestClient) -> None:
        result = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")
        entry = result["entry"]

        assert entry["rule"] == "split-5050"
        assert entry["paid_by"] == {"yarden": "-50.00"}
        assert [(s["person"], s["amount"], s["bucket"]) for s in entry["shares"]] == [
            ("yarden", "-25.00", "fun-money"),
            ("dana", "-25.00", "fun-money"),
        ]
        assert len(result["commit"]) == 40  # a real sha, so the client can link to the diff

    def test_a_more_specific_rule_wins(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-284.51", payee="שופרסל דיל", date="2026-07-15")["entry"]

        assert entry["rule"] == "groceries"
        assert {s["bucket"] for s in entry["shares"]} == {"groceries"}
        assert sum(D(s["amount"]) for s in entry["shares"]) == D("-284.51")

    def test_an_explicit_split_overrides_the_rules(self, client: TestClient) -> None:
        entry = post_entry(
            client,
            amount="-100.00",
            payee="ספרים",
            date="2026-07-16",
            shares=[
                {"person": "yarden", "amount": "-80.00", "bucket": "fun-money"},
                {"person": "dana", "amount": "-20.00", "bucket": "fun-money"},
            ],
        )["entry"]

        assert entry["rule"] is None
        assert entry["shares"][0]["amount"] == "-80.00"

    def test_a_rule_still_picks_the_bucket_under_an_explicit_split(
        self, client: TestClient
    ) -> None:
        """The form always sends the split it shows. The bucket is a separate decision and
        the rule must keep making it, or every explicit split would need a bucket typed."""
        entry = post_entry(
            client,
            amount="-100.00",
            payee="שופרסל דיל",
            date="2026-07-14",
            shares=[{"person": "yarden", "amount": "-100.00"}],
        )["entry"]
        assert entry["rule"] == "groceries"
        assert entry["shares"] == [{"person": "yarden", "amount": "-100.00", "bucket": "groceries"}]

    def test_a_split_that_does_not_add_up_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/budgets/joint/entries",
            json={
                "amount": "-100.00",
                "payee": "ספרים",
                "shares": [{"person": "yarden", "amount": "-80.00", "bucket": "fun-money"}],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_data"
        assert "shares sum to -80.00" in response.json()["error"]["message"]

    def test_preview_does_not_write_anything(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/budgets/joint/entries/preview",
            json={"amount": "-50.00", "payee": "קפה גרג"},
        )
        assert response.status_code == 200
        assert response.json()["rule"] == "split-5050"

        listing = client.get("/api/v1/budgets/joint/entries")
        assert listing.json()["total"] == 0

    def test_entry_history_comes_from_git(self, client: TestClient) -> None:
        entry_id = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"][
            "id"
        ]
        client.patch(f"/api/v1/budgets/joint/entries/{entry_id}", json={"payee": "קפה אחר"})

        history = client.get(f"/api/v1/budgets/joint/entries/{entry_id}/history").json()
        assert len(history["commits"]) == 2
        assert history["commits"][0]["author_name"] == "Dev User"

    def test_filters_narrow_the_ledger(self, client: TestClient) -> None:
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14", tags=["coffee"])
        post_entry(client, amount="-284.51", payee="שופרסל דיל", date="2026-08-02")

        assert client.get("/api/v1/budgets/joint/entries?month=2026-07").json()["total"] == 1
        assert client.get("/api/v1/budgets/joint/entries?bucket=groceries").json()["total"] == 1
        assert client.get("/api/v1/budgets/joint/entries?tag=coffee").json()["total"] == 1
        assert client.get("/api/v1/budgets/joint/entries?payee=שופרסל").json()["total"] == 1


class TestReceipts:
    def test_a_receipt_records_its_lines(self, client: TestClient) -> None:
        entry = post_entry(
            client,
            amount="-120.00",
            payee="שופרסל דיל",
            date="2026-07-14",
            items=[
                {"label": "חלב", "amount": "-20.00"},
                {"label": "יין", "amount": "-100.00"},
            ],
        )["entry"]
        assert [item["label"] for item in entry["items"]] == ["חלב", "יין"]

    def test_lines_must_sum_to_the_entry(self, client: TestClient) -> None:
        """Otherwise the receipt describes a different purchase from the one recorded."""
        response = client.post(
            "/api/v1/budgets/joint/entries",
            json={
                "amount": "-120.00",
                "payee": "שופרסל דיל",
                "items": [{"label": "חלב", "amount": "-20.00"}],
            },
        )
        assert response.status_code == 422
        assert "items sum to -20.00" in response.json()["error"]["message"]

    def test_a_line_can_go_to_a_different_bucket(self, client: TestClient) -> None:
        """A supermarket run is groceries and a bottle of wine; the entry split cannot say so."""
        entry = post_entry(
            client,
            amount="-120.00",
            payee="שופרסל דיל",
            date="2026-07-14",
            items=[
                {
                    "label": "חלב",
                    "amount": "-20.00",
                    "shares": [{"person": "yarden", "amount": "-20.00", "bucket": "groceries"}],
                },
                {
                    "label": "יין",
                    "amount": "-100.00",
                    "shares": [{"person": "yarden", "amount": "-100.00", "bucket": "fun-money"}],
                },
            ],
        )["entry"]

        by_bucket = {share["bucket"]: share["amount"] for share in entry["shares"]}
        assert by_bucket == {"groceries": "-20.00", "fun-money": "-100.00"}

    def test_splitting_only_some_lines_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/budgets/joint/entries",
            json={
                "amount": "-120.00",
                "payee": "שופרסל דיל",
                "items": [
                    {
                        "label": "חלב",
                        "amount": "-20.00",
                        "shares": [{"person": "yarden", "amount": "-20.00", "bucket": "groceries"}],
                    },
                    {"label": "יין", "amount": "-100.00"},
                ],
            },
        )
        assert response.status_code == 422


class TestPayeeSuggestions:
    def test_a_literal_path_is_not_matched_as_an_entry_id(self, client: TestClient) -> None:
        """/entries/payees must not be routed to /entries/{entry_id}.

        FastAPI matches in registration order, so a literal segment declared after a path
        parameter is shadowed by it — the request would 404 as a missing entry.
        """
        response = client.get("/api/v1/budgets/joint/entries/payees")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)

    def test_it_suggests_the_repeated_amount_when_there_is_one(self, client: TestClient) -> None:
        for _ in range(3):
            post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")
        post_entry(client, amount="-92.00", payee="קפה גרג", date="2026-07-20")

        [coffee] = client.get("/api/v1/budgets/joint/entries/payees?q=קפה").json()
        assert coffee["count"] == 4
        assert coffee["amount"] == "-50.00"
        assert coffee["basis"] == "mode"
        assert coffee["bucket"] == "fun-money"

    def test_it_falls_back_to_the_latest_when_every_visit_differs(self, client: TestClient) -> None:
        """A mean is meaningless for a shop where you buy something different each time."""
        post_entry(client, amount="-120.00", payee="שופרסל דיל", date="2026-07-10")
        post_entry(client, amount="-284.51", payee="שופרסל דיל", date="2026-07-27")

        [shop] = client.get("/api/v1/budgets/joint/entries/payees?q=שופרסל").json()
        assert shop["basis"] == "latest"
        assert shop["amount"] == "-284.51"

    def test_frequency_outranks_a_single_recent_visit(self, client: TestClient) -> None:
        for _ in range(4):
            post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-01")
        post_entry(client, amount="-30.00", payee="פלאפל", date="2026-07-27")

        suggestions = client.get("/api/v1/budgets/joint/entries/payees").json()
        assert suggestions[0]["payee"] == "קפה גרג"


class TestBalancesAndSettling:
    def test_the_coffee_example_end_to_end(self, client: TestClient) -> None:
        """One shared coffee leaves Dana owing Yarden 25, through the real HTTP surface."""
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        assert {b["person"]: b["net"] for b in sheet["balances"]} == {
            "yarden": "25.00",
            "dana": "-25.00",
        }
        assert sheet["settle_up"] == [
            {"payer": "dana", "payee": "yarden", "amount": "25.00", "currency": "ILS"}
        ]

    def test_settling_clears_the_balance(self, client: TestClient) -> None:
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")
        # Yarden is owed, so Yarden settling *to* Dana is the wrong direction; the API
        # records whatever is asked, and the balance simply reflects it.
        response = client.post(
            "/api/v1/budgets/joint/settle",
            json={"to": "dana", "amount": "25.00", "date": "2026-07-20"},
        )
        assert response.status_code == 200
        assert response.json()["entry"]["kind"] == "settlement"

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        assert {b["person"]: b["net"] for b in sheet["balances"]} == {
            "yarden": "50.00",
            "dana": "-50.00",
        }

    def test_the_person_who_is_owed_can_record_the_payment(self, client: TestClient) -> None:
        """Dana may not use the app; Yarden still has to be able to record that she paid.

        The recorded entry must have Dana as the payer, not the caller — recording it the
        other way would move the balance further in the wrong direction.
        """
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")

        response = client.post(
            "/api/v1/budgets/joint/settle",
            json={"payer": "dana", "to": "yarden", "amount": "25.00", "date": "2026-07-20"},
        )
        assert response.status_code == 200
        assert response.json()["entry"]["paid_by"] == {"dana": "-25.00"}

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        assert all(b["net"] == "0.00" for b in sheet["balances"])

    def test_you_cannot_record_a_settlement_between_other_people(self, client: TestClient) -> None:
        client.put(
            "/api/v1/budgets/joint/members",
            json=[
                {"person": "yarden", "name": "Yarden", "github": "dev"},
                {"person": "dana", "name": "Dana", "github": "dana-example"},
                {"person": "noa", "name": "Noa", "github": None},
            ],
        )
        response = client.post(
            "/api/v1/budgets/joint/settle",
            json={"payer": "dana", "to": "noa", "amount": "25.00"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "not_a_party"

    def test_you_cannot_settle_with_yourself(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/budgets/joint/settle", json={"to": "yarden", "amount": "25.00"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "self_settlement"


class TestMonths:
    def test_assigning_and_spending_move_the_envelope(self, client: TestClient) -> None:
        assign = client.put(
            "/api/v1/budgets/joint/months/2026-07/assign",
            json={"bucket": "fun-money", "amount": "400.00"},
        )
        assert assign.status_code == 200

        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")

        month = client.get("/api/v1/budgets/joint/months/2026-07").json()
        fun = next(b for b in month["buckets"] if b["bucket"] == "fun-money")
        # The bucket is shared, so its own figures are the household's. Each funder's slice
        # is in `funders` — which is what makes an envelope able to be red for one person.
        assert fun["assigned"] == "400.00"
        assert fun["activity"] == "-50.00"

        mine = next(f for f in fun["funders"] if f["person"] == "yarden")
        theirs = next(f for f in fun["funders"] if f["person"] == "dana")
        assert mine["activity"] == "-25.00"
        assert theirs["activity"] == "-25.00"
        assert mine["assigned"] == "400.00"
        assert theirs["assigned"] == "0.00"
        # 400 funded by one person, 50 spent by the household.
        assert fun["available"] == "350.00"
        # And this is the whole point of the model: the same envelope is +375 for the person
        # who funded it and -25 for the one who did not, at the same time.
        assert mine["available"] == "375.00"
        assert theirs["available"] == "-25.00"

    def test_auto_assign_tops_every_bucket_up_to_its_target(self, client: TestClient) -> None:
        """Payday: funding envelopes one at a time is the chore this removes."""
        response = client.post(
            "/api/v1/budgets/joint/months/2026-07/auto-assign",
            json={"strategy": "underfunded"},
        )
        assert response.status_code == 200

        assigned = {b["bucket"]: b["assigned"] for b in response.json()["buckets"]}
        # Only buckets carrying a target are funded; the seed gives neither one a target.
        assert set(assigned) == {"fun-money", "groceries"}

    def test_auto_assign_never_claws_back_a_larger_assignment(self, client: TestClient) -> None:
        """Someone who deliberately over-assigned should not have it silently reduced."""
        client.put(
            "/api/v1/budgets/joint/buckets/fun-money",
            json={
                "id": "fun-money",
                "name": "בילויים",
                "target": {"kind": "monthly", "amount": "400.00"},
            },
        )
        client.put(
            "/api/v1/budgets/joint/months/2026-07/assign",
            json={"bucket": "fun-money", "amount": "900.00"},
        )
        response = client.post(
            "/api/v1/budgets/joint/months/2026-07/auto-assign",
            json={"strategy": "underfunded"},
        )
        fun = next(b for b in response.json()["buckets"] if b["bucket"] == "fun-money")
        assert fun["assigned"] == "900.00"

    def test_moving_money_debits_one_bucket_and_credits_the_other(self, client: TestClient) -> None:
        client.put(
            "/api/v1/budgets/joint/months/2026-07/assign",
            json={"bucket": "fun-money", "amount": "400.00"},
        )
        response = client.post(
            "/api/v1/budgets/joint/months/2026-07/move",
            json={"source": "fun-money", "target": "groceries", "amount": "150.00"},
        )
        assert response.status_code == 200

        assigned = {b["bucket"]: b["assigned"] for b in response.json()["buckets"]}
        assert assigned["fun-money"] == "250.00"
        assert assigned["groceries"] == "150.00"

    def test_moving_more_than_a_bucket_holds_is_refused(self, client: TestClient) -> None:
        client.put(
            "/api/v1/budgets/joint/months/2026-07/assign",
            json={"bucket": "fun-money", "amount": "100.00"},
        )
        response = client.post(
            "/api/v1/budgets/joint/months/2026-07/move",
            json={"source": "fun-money", "target": "groceries", "amount": "500.00"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "not_enough_available"

    def test_moving_money_to_the_same_bucket_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/budgets/joint/months/2026-07/move",
            json={"source": "fun-money", "target": "fun-money", "amount": "10.00"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "same_bucket"

    def test_assigning_to_an_unknown_bucket_is_rejected(self, client: TestClient) -> None:
        response = client.put(
            "/api/v1/budgets/joint/months/2026-07/assign",
            json={"bucket": "nonexistent", "amount": "400.00"},
        )
        assert response.status_code == 404


class TestMembers:
    def test_a_person_can_be_added(self, client: TestClient) -> None:
        response = client.put(
            "/api/v1/budgets/joint/members",
            json=[
                {"person": "yarden", "name": "Yarden", "github": "dev"},
                {"person": "dana", "name": "Dana", "github": "dana-example"},
                {"person": "noa", "name": "Noa", "github": None},
            ],
        )
        assert response.status_code == 200
        assert [m["person"] for m in response.json()] == ["yarden", "dana", "noa"]

        # The change lands in budget.yaml, so the next read sees it.
        assert len(client.get("/api/v1/budgets/joint/members").json()) == 3

    def test_removing_someone_who_still_has_entries_is_refused(self, client: TestClient) -> None:
        """Dropping them would orphan their shares and silently move every balance."""
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")

        response = client.put(
            "/api/v1/budgets/joint/members",
            json=[{"person": "yarden", "name": "Yarden", "github": "dev"}],
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "person_in_use"
        assert "dana" in response.json()["error"]["details"]["people"]

    def test_duplicate_person_ids_are_refused(self, client: TestClient) -> None:
        response = client.put(
            "/api/v1/budgets/joint/members",
            json=[
                {"person": "yarden", "name": "Yarden", "github": "dev"},
                {"person": "yarden", "name": "Other", "github": None},
            ],
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "duplicate_person"

    def test_a_budget_cannot_be_left_with_nobody(self, client: TestClient) -> None:
        response = client.put("/api/v1/budgets/joint/members", json=[])
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "empty_members"


class TestErrorShape:
    def test_every_error_uses_the_same_envelope(self, client: TestClient) -> None:
        response = client.get("/api/v1/budgets/joint/entries/01K0000000000000000000000A")
        assert response.status_code == 404
        body = response.json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"code", "message", "details"}

    def test_a_malformed_body_uses_the_envelope_too(self, client: TestClient) -> None:
        """FastAPI rejects these before any route runs, and its default shape is `detail`.

        A client reading `error.message` got an object back and rendered "[object Object]".
        """
        response = client.post("/api/v1/budgets", json={"slug": "BAD SLUG!", "repo": "nope"})
        assert response.status_code == 422

        error = response.json()["error"]
        assert error["code"] == "invalid_request"
        assert isinstance(error["message"], str) and error["message"]
        assert "slug" in error["details"]["fields"]
        assert "repo" in error["details"]["fields"]

    def test_an_unparseable_body_still_reads_as_a_sentence(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/budgets/joint/entries",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        assert isinstance(response.json()["error"]["message"], str)


class TestPersonIdDerivation:
    """An invite derives a person id from a GitHub login without colliding."""

    def test_a_login_becomes_a_slug(self) -> None:
        from money.api.routes.github_routes import _person_id_from

        assert _person_id_from("Yarden-zamir", set()) == "yarden-zamir"
        assert _person_id_from("dana.example", set()) == "dana-example"

    def test_a_taken_id_gets_a_suffix(self) -> None:
        from money.api.routes.github_routes import _person_id_from

        assert _person_id_from("dana", {"dana"}) == "dana-2"
        assert _person_id_from("dana", {"dana", "dana-2"}) == "dana-3"


class TestHealth:
    def test_liveness_does_not_touch_the_data_repo(self, client: TestClient) -> None:
        assert client.get("/healthz").json() == {"status": "ok"}

    def test_readiness_reports_the_data_branch(self, client: TestClient) -> None:
        assert client.get("/readyz").json()["data_branch"] == "main"


class TestAssigningManyAtOnce:
    """Every assignment for a person and month lives in one file, so writing them one at a
    time was a fetch, commit and push per bucket — eight buckets was about fourteen seconds
    and eight commits for one button press."""

    def commits(self, client: TestClient) -> int:
        return len(
            client.get("/api/v1/budgets/joint/history", params={"limit": 200}).json()["events"]
        )

    def test_auto_assign_writes_one_commit(self, client: TestClient) -> None:
        client.put(
            "/api/v1/budgets/joint/buckets/groceries",
            json={
                "id": "groceries",
                "name": "מכולת",
                "target": {"kind": "monthly", "amount": "1200"},
            },
        )
        client.put(
            "/api/v1/budgets/joint/buckets/fun-money",
            json={
                "id": "fun-money",
                "name": "בילויים",
                "target": {"kind": "monthly", "amount": "400"},
            },
        )
        before = self.commits(client)

        response = client.post(
            "/api/v1/budgets/joint/months/2026-08/auto-assign", json={"strategy": "underfunded"}
        )
        assert response.status_code == 200, response.text

        funded = {b["bucket"]: b["assigned"] for b in response.json()["buckets"]}
        assert funded["groceries"] == "1200.00"
        assert funded["fun-money"] == "400.00"
        assert self.commits(client) - before == 1, "two buckets funded must be one commit"

    def test_funding_nothing_writes_nothing(self, client: TestClient) -> None:
        """No bucket has a target, so there is nothing to top up. It must not commit an
        empty change just to have done something."""
        before = self.commits(client)
        client.post(
            "/api/v1/budgets/joint/months/2026-08/auto-assign", json={"strategy": "underfunded"}
        )
        assert self.commits(client) == before

    def test_moving_money_is_one_commit(self, client: TestClient) -> None:
        """Both sides together. Two commits left money taken from one envelope and not yet in
        the other — observable to anyone reading the repo, and the thing this endpoint exists
        to prevent."""
        client.put(
            "/api/v1/budgets/joint/months/2026-08/assign",
            json={"bucket": "groceries", "amount": "500.00"},
        )
        before = self.commits(client)

        response = client.post(
            "/api/v1/budgets/joint/months/2026-08/move",
            json={"source": "groceries", "target": "fun-money", "amount": "200.00"},
        )
        assert response.status_code == 200, response.text

        assigned = {b["bucket"]: b["assigned"] for b in response.json()["buckets"]}
        assert assigned["groceries"] == "300.00"
        assert assigned["fun-money"] == "200.00"
        assert self.commits(client) - before == 1


class TestReorderingBuckets:
    """A drag can shift every bucket it passes, and they all live in one file."""

    def commits(self, client: TestClient) -> int:
        page = client.get("/api/v1/budgets/joint/history", params={"limit": 200})
        return len(page.json()["events"])

    def order_of(self, client: TestClient) -> list[str]:
        return [b["id"] for b in client.get("/api/v1/budgets/joint/buckets").json()]

    def test_a_whole_reorder_is_one_commit(self, client: TestClient) -> None:
        before = self.commits(client)

        response = client.put(
            "/api/v1/budgets/joint/buckets/order",
            json={
                "order": [
                    {"bucket": "fun-money", "group": "Fun"},
                    {"bucket": "groceries", "group": "Fun"},
                ]
            },
        )
        assert response.status_code == 200, response.text

        assert self.order_of(client) == ["fun-money", "groceries"]
        assert self.commits(client) - before == 1, "one gesture must be one commit"

    def test_position_restarts_per_group(self, client: TestClient) -> None:
        """Order is the index *within* a group, not in the flat list — otherwise the second
        group starts at whatever number the first one ended on and sorts oddly."""
        client.put(
            "/api/v1/budgets/joint/buckets/order",
            json={
                "order": [
                    {"bucket": "fun-money", "group": "A"},
                    {"bucket": "groceries", "group": "B"},
                ]
            },
        )
        buckets = {b["id"]: b for b in client.get("/api/v1/budgets/joint/buckets").json()}
        assert buckets["fun-money"]["order"] == 0
        assert buckets["groceries"]["order"] == 0

    def test_it_cannot_rename_or_retarget(self, client: TestClient) -> None:
        """Position is the only thing a drag means. A wholesale replace would let a client
        holding a stale list undo somebody else's rename in passing."""
        client.put(
            "/api/v1/budgets/joint/buckets/groceries",
            json={
                "id": "groceries",
                "name": "Renamed",
                "target": {"kind": "monthly", "amount": "50"},
            },
        )
        client.put(
            "/api/v1/budgets/joint/buckets/order",
            json={"order": [{"bucket": "groceries", "group": "Elsewhere"}]},
        )

        groceries = next(
            b for b in client.get("/api/v1/budgets/joint/buckets").json() if b["id"] == "groceries"
        )
        assert groceries["name"] == "Renamed"
        assert groceries["target"]["amount"] == "50.00"
        assert groceries["group"] == "Elsewhere"

    def test_omitted_buckets_are_left_alone(self, client: TestClient) -> None:
        """Archived buckets are not on screen to be dragged, so leaving them out of the list
        must not move them."""
        before = {b["id"]: b["group"] for b in client.get("/api/v1/budgets/joint/buckets").json()}

        client.put(
            "/api/v1/budgets/joint/buckets/order",
            json={"order": [{"bucket": "groceries", "group": "Moved"}]},
        )

        after = {b["id"]: b["group"] for b in client.get("/api/v1/budgets/joint/buckets").json()}
        assert after["fun-money"] == before["fun-money"]
        assert set(after) == set(before), "nothing may be created or dropped"

    def test_an_unknown_bucket_is_refused(self, client: TestClient) -> None:
        response = client.put(
            "/api/v1/budgets/joint/buckets/order",
            json={"order": [{"bucket": "nope", "group": None}]},
        )
        assert response.status_code == 404

    def test_repeating_an_order_already_in_effect_writes_nothing(self, client: TestClient) -> None:
        """A drag that ends where it started must not add a commit saying so.

        Applied twice, not once: seeded buckets carry no explicit position and fall back to
        sorting by name, so the *first* reorder genuinely changes the file by pinning them.
        """
        wanted = {
            "order": [
                {"bucket": "fun-money", "group": "Fun"},
                {"bucket": "groceries", "group": "Fun"},
            ]
        }
        client.put("/api/v1/budgets/joint/buckets/order", json=wanted)
        before = self.commits(client)

        client.put("/api/v1/budgets/joint/buckets/order", json=wanted)
        assert self.commits(client) == before

    def test_order_is_not_matched_as_a_bucket_id(self, client: TestClient) -> None:
        """`/buckets/order` is declared before `/buckets/{bucket_id}`. Reversed, a reorder
        would be read as an attempt to create a bucket literally called "order"."""
        assert "order" not in self.order_of(client)


class TestActingAsSomebodyElse:
    """Switching person is a testing affordance, and it must not be an impersonation hole.

    The whole safeguard is one rule: only a member with no GitHub login can be acted as. A
    placeholder is a stand-in nobody can sign in as; a real account always speaks for itself.
    Without that, anyone with repo access could attribute their spending to their partner —
    exactly what the ledger exists to record honestly.

    Tested against `_acting_as` directly, because the client fixture replaces `budget_context`
    wholesale and an integration test would exercise the override rather than the rule.
    """

    @staticmethod
    def store_with(members: list[dict], tmp_path) -> BudgetStore:
        from tests.test_onboarding import seed_remote

        yaml = "name: joint\ncurrency: ILS\nstart_month: 2026-07\nmembers:\n" + "".join(
            f"  - person: {m['person']}\n    name: {m['name']}\n"
            + (f"    github: {m['github']}\n" if m.get("github") else "")
            for m in members
        )
        return BudgetStore(seed_remote(tmp_path, yaml))

    def test_a_real_member_cannot_be_acted_as(self, tmp_path) -> None:
        store = self.store_with(
            [{"person": "dana", "name": "Dana", "github": "dana-example"}], tmp_path
        )
        with pytest.raises(ApiError) as caught:
            _acting_as(store, "dana")
        assert caught.value.status == 403
        assert "cannot be acted as" in caught.value.message

    def test_an_unknown_member_is_a_404(self, tmp_path) -> None:
        store = self.store_with([{"person": "dana", "name": "Dana"}], tmp_path)
        with pytest.raises(ApiError) as caught:
            _acting_as(store, "nobody")
        assert caught.value.status == 404

    def test_a_placeholder_member_can_be_acted_as(self, tmp_path) -> None:
        """No GitHub login, so nobody can sign in as them and nobody is impersonated."""
        store = self.store_with([{"person": "ghost", "name": "Ghost"}], tmp_path)
        assert _acting_as(store, "ghost") == "ghost"

    def test_no_header_means_the_signed_in_account(self, tmp_path) -> None:
        store = self.store_with([{"person": "ghost", "name": "Ghost"}], tmp_path)
        assert _acting_as(store, None) is None


class TestSearch:
    def test_every_word_must_match_somewhere_on_the_entry(self, client: TestClient) -> None:
        post_entry(client, amount="-50.00", payee="קפה גרג", note="with Dana", date="2026-07-14")
        post_entry(client, amount="-30.00", payee="קפה גרג", date="2026-07-15")
        post_entry(client, amount="-90.00", payee="Pizza", tags=["takeaway"], date="2026-07-16")

        by_note = client.get("/api/v1/budgets/joint/entries", params={"q": "גרג dana"}).json()
        assert [e["note"] for e in by_note["entries"]] == ["with Dana"]

        by_tag = client.get("/api/v1/budgets/joint/entries", params={"q": "takeaway"}).json()
        assert [e["payee"] for e in by_tag["entries"]] == ["Pizza"]

        nothing = client.get("/api/v1/budgets/joint/entries", params={"q": "גרג pizza"}).json()
        assert nothing["total"] == 0

    def test_kind_narrows_the_ledger(self, client: TestClient) -> None:
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")
        post_entry(client, amount="12000.00", payee="Employer", kind="income", date="2026-07-28")

        income = client.get("/api/v1/budgets/joint/entries", params={"kind": "income"}).json()
        assert [e["payee"] for e in income["entries"]] == ["Employer"]


class TestComments:
    def test_a_thread_is_appended_to_and_attributed(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/comments"

        first = client.post(url, json={"text": "did you keep the receipt?"})
        assert first.status_code == 200, first.text
        second = client.post(url, json={"text": "yes, attaching it"})

        thread = second.json()["comments"]
        assert [c["text"] for c in thread] == ["did you keep the receipt?", "yes, attaching it"]
        assert {c["author"] for c in thread} == {"yarden"}
        assert thread[0]["id"] < thread[1]["id"]  # ULIDs keep the order it was said in
        assert thread[0]["at"].endswith("Z") or "+" in thread[0]["at"]  # absolute, not local

        listed = client.get(url).json()
        assert listed == second.json()

    def test_a_comment_is_a_commit_the_history_can_name(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        client.post(f"/api/v1/budgets/joint/entries/{entry['id']}/comments", json={"text": "hi"})

        feed = client.get("/api/v1/budgets/joint/history").json()["events"]
        assert feed[0]["kind"] == "comment"
        assert feed[0]["entry_id"] == entry["id"]

    def test_only_the_author_can_remove_a_comment(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/comments"
        comment = client.post(url, json={"text": "oops"}).json()["comments"][0]

        # Something Dana said, written through the store because the client fixture pins
        # the caller to Yarden. The route's rule is what is under test, not the fixture.
        from datetime import UTC, datetime

        from money.domain.models import Comment

        context = client.app.dependency_overrides[budget_context]()
        hers = Comment(id=new_id(), author="dana", at=datetime.now(UTC), text="mine")
        context.store.add_comment(entry["id"], hers, context.actor)

        not_mine = client.delete(f"{url}/{hers.id}")
        assert not_mine.status_code == 403
        assert len(client.get(url).json()["comments"]) == 2

        mine = client.delete(f"{url}/{comment['id']}")
        assert mine.status_code == 200
        assert [c["id"] for c in mine.json()["comments"]] == [hers.id]

    def test_the_list_carries_counts_for_badges(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        post_entry(client, amount="-30.00", payee="Quiet", date="2026-07-15")
        client.post(f"/api/v1/budgets/joint/entries/{entry['id']}/comments", json={"text": "a"})
        client.post(f"/api/v1/budgets/joint/entries/{entry['id']}/comments", json={"text": "b"})

        listed = client.get("/api/v1/budgets/joint/entries").json()
        assert listed["extras"] == {entry["id"]: {"comments": 2, "attachments": 0}}


class TestAttachments:
    JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64

    def test_a_receipt_photo_is_committed_beside_the_entry(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/attachments"

        uploaded = client.post(url, content=self.JPEG, headers={"Content-Type": "image/jpeg"})
        assert uploaded.status_code == 200, uploaded.text
        [attachment] = uploaded.json()["attachments"]
        assert attachment["name"].endswith(".jpg")
        assert attachment["content_type"] == "image/jpeg"
        assert attachment["size"] == len(self.JPEG)

        fetched = client.get(f"{url}/{attachment['name']}")
        assert fetched.status_code == 200
        assert fetched.content == self.JPEG
        assert fetched.headers["content-type"] == "image/jpeg"
        assert "immutable" in fetched.headers["cache-control"]

        feed = client.get("/api/v1/budgets/joint/history").json()["events"]
        assert feed[0]["kind"] == "attachment"

        listed = client.get("/api/v1/budgets/joint/entries").json()
        assert listed["extras"][entry["id"]]["attachments"] == 1

    def test_a_generated_client_names_the_type_in_the_query(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/attachments"

        uploaded = client.post(
            url,
            content=b"%PDF-1.4 ...",
            params={"media_type": "application/pdf"},
            headers={"Content-Type": "application/octet-stream"},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["attachments"][0]["name"].endswith(".pdf")

    def test_anything_but_a_receipt_shaped_file_is_refused(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/attachments"

        refused = client.post(url, content=b"#!/bin/sh", headers={"Content-Type": "text/x-sh"})
        assert refused.status_code == 400
        assert refused.json()["error"]["code"] == "unsupported_attachment"
        assert client.get(url).json()["attachments"] == []

    def test_a_removed_attachment_is_gone_from_the_list_and_the_url(
        self, client: TestClient
    ) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/attachments"
        [attachment] = client.post(
            url, content=self.JPEG, headers={"Content-Type": "image/jpeg"}
        ).json()["attachments"]

        removed = client.delete(f"{url}/{attachment['name']}")
        assert removed.status_code == 200
        assert removed.json()["attachments"] == []
        assert client.get(f"{url}/{attachment['name']}").status_code == 404

    def test_a_name_cannot_climb_out_of_the_entry_directory(self, client: TestClient) -> None:
        entry = post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")["entry"]
        url = f"/api/v1/budgets/joint/entries/{entry['id']}/attachments"

        # The router never matches a name with a slash in it, so the request falls through
        # to the SPA — which is fine, as long as the budget file is not what comes back.
        answered = client.get(f"{url}/..%2Fbudget.yaml")
        assert "start_month" not in answered.text

        context = client.app.dependency_overrides[budget_context]()
        assert context.store.attachment(entry["id"], "../budget.yaml") is None
        assert context.store.attachment(entry["id"], "..") is None


class TestCurrency:
    """Conversion is a decision: at the day's rate, at a typed rate, or not yet."""

    @pytest.fixture(autouse=True)
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        """The ECB, answering 3.7 shekels to the dollar and nothing for anything else."""
        calls: dict = {"count": 0}

        def fake(currency: str, base: str, day) -> Decimal | None:
            calls["count"] += 1
            return Decimal("3.7000") if (currency, base) == ("USD", "ILS") else None

        monkeypatch.setattr("money.api.fx.fetch_rate", fake)
        return calls

    def test_a_foreign_entry_converts_at_the_days_rate_and_commits_it(
        self, client: TestClient, provider: dict
    ) -> None:
        entry = post_entry(
            client, amount="-50.00", payee="Amazon", currency="USD", date="2026-07-14"
        )["entry"]
        assert entry["fx"] == {
            "rate": "3.7000",
            "amount": "-185.00",
            "at": "2026-07-14",
            "source": "table",
        }
        # The rate landed in the table, so the next conversion on that day asks nobody.
        context = client.app.dependency_overrides[budget_context]()
        assert "rates.yaml" in context.store.repo.list_files("rates.yaml")
        assert context.store.rate("USD", date(2026, 7, 14)) == Decimal("3.7000")
        post_entry(client, amount="-10.00", payee="Amazon", currency="USD", date="2026-07-14")
        assert provider["count"] == 1

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        assert {b["person"]: b["net"] for b in sheet["balances"]} == {
            "yarden": "111.00",  # (185 + 37) / 2
            "dana": "-111.00",
        }

    def test_a_typed_rate_stays_on_the_entry_and_out_of_the_table(self, client: TestClient) -> None:
        entry = post_entry(
            client,
            amount="-50.00",
            payee="Amazon",
            currency="USD",
            date="2026-07-14",
            fx={"mode": "manual", "rate": "3.55"},
        )["entry"]
        assert entry["fx"]["source"] == "manual"
        assert entry["fx"]["amount"] == "-177.50"
        context = client.app.dependency_overrides[budget_context]()
        assert context.store.rate("USD", date(2026, 7, 14)) is None

    def test_unconverted_money_is_a_second_column(self, client: TestClient) -> None:
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")
        post_entry(
            client,
            amount="-10.00",
            payee="Diner",
            currency="USD",
            date="2026-07-15",
            fx={"mode": "none"},
        )

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        by_person = {b["person"]: b for b in sheet["balances"]}
        assert by_person["yarden"]["net"] == "25.00"
        assert by_person["yarden"]["foreign"] == {"USD": "5.00"}
        assert [(p["currency"], p["amount"]) for p in sheet["settle_up"]] == [
            ("ILS", "25.00"),
            ("USD", "5.00"),
        ]

        month = client.get("/api/v1/budgets/joint/months/2026-07").json()
        fun = next(b for b in month["buckets"] if b["bucket"] == "fun-money")
        assert fun["activity"] == "-50.00"
        assert fun["foreign"] == {"USD": "-10.00"}

        listed = client.get("/api/v1/budgets/joint/entries", params={"unconverted": "true"}).json()
        assert [e["payee"] for e in listed["entries"]] == ["Diner"]

    def test_no_rate_means_refuse_not_guess(self, client: TestClient) -> None:
        refused = client.post(
            "/api/v1/budgets/joint/entries",
            json={"amount": "-50.00", "payee": "Bar", "currency": "GBP", "date": "2026-07-14"},
        )
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "no_rate"

        kept = post_entry(
            client,
            amount="-50.00",
            payee="Bar",
            currency="GBP",
            date="2026-07-14",
            fx={"mode": "none"},
        )["entry"]
        assert kept["fx"] is None

    def test_the_budget_currency_takes_no_choice(self, client: TestClient) -> None:
        refused = client.post(
            "/api/v1/budgets/joint/entries",
            json={"amount": "-50.00", "payee": "Bar", "fx": {"mode": "none"}},
        )
        assert refused.json()["error"]["code"] == "fx_not_needed"

    def test_converting_one_entry_later_uses_the_conversion_day(
        self, client: TestClient, provider: dict
    ) -> None:
        entry = post_entry(
            client,
            amount="-10.00",
            payee="Diner",
            currency="USD",
            date="2026-07-15",
            fx={"mode": "none"},
        )["entry"]
        result = client.post(
            f"/api/v1/budgets/joint/entries/{entry['id']}/convert", json={"date": "2026-07-20"}
        )
        assert result.status_code == 200, result.text
        assert result.json()["fx"]["at"] == "2026-07-20"
        assert result.json()["fx"]["amount"] == "-37.00"

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        yarden = next(b for b in sheet["balances"] if b["person"] == "yarden")
        assert yarden["net"] == "18.50"
        assert yarden["foreign"] == {}

        again = client.post(f"/api/v1/budgets/joint/entries/{entry['id']}/convert", json={})
        assert again.json()["error"]["code"] == "already_converted"

        feed = client.get("/api/v1/budgets/joint/history").json()["events"]
        assert feed[0]["kind"] == "convert"
        assert feed[0]["entry_id"] == entry["id"]

    def test_converting_a_bucket_is_one_commit_at_one_rate(self, client: TestClient) -> None:
        for amount in ("-10.00", "-20.00"):
            post_entry(
                client,
                amount=amount,
                payee="Diner",
                currency="USD",
                date="2026-07-15",
                fx={"mode": "none"},
            )
        # One spanning two buckets, and one in shekels that must be left alone.
        spanning = post_entry(
            client,
            amount="-30.00",
            payee="Mixed",
            currency="USD",
            date="2026-07-16",
            fx={"mode": "none"},
            shares=[
                {"person": "yarden", "amount": "-15.00", "bucket": "fun-money"},
                {"person": "dana", "amount": "-15.00", "bucket": "groceries"},
            ],
        )["entry"]
        post_entry(client, amount="-50.00", payee="קפה גרג", date="2026-07-14")

        before = len(client.get("/api/v1/budgets/joint/history").json()["events"])
        result = client.post(
            "/api/v1/budgets/joint/buckets/fun-money/convert",
            json={"currency": "USD", "rate": "3.5"},
        )
        assert result.status_code == 200, result.text
        assert len(result.json()["converted"]) == 3
        assert result.json()["spanning"] == [spanning["id"]]
        after = client.get("/api/v1/budgets/joint/history").json()["events"]
        assert len(after) == before + 1
        assert after[0]["subject"] == "convert: 3 USD entries in בילויים at 3.5000"

        month = client.get("/api/v1/budgets/joint/months/2026-07").json()
        fun = next(b for b in month["buckets"] if b["bucket"] == "fun-money")
        assert fun["foreign"] == {}
        assert fun["activity"] == "-207.50"  # 50 + 3.5 × (10 + 20 + 15, the half in this bucket)

    def test_a_settlement_in_dollars_clears_the_dollar_debt(self, client: TestClient) -> None:
        post_entry(
            client,
            amount="-10.00",
            payee="Diner",
            currency="USD",
            date="2026-07-15",
            fx={"mode": "none"},
        )
        settled = client.post(
            "/api/v1/budgets/joint/settle",
            json={"payer": "dana", "to": "yarden", "amount": "5.00", "currency": "USD"},
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["entry"]["currency"] == "USD"
        assert settled.json()["entry"]["fx"] is None

        sheet = client.get("/api/v1/budgets/joint/balances").json()
        assert all(b["foreign"] == {} for b in sheet["balances"])
        assert sheet["settle_up"] == []

    def test_the_rate_lookup_commits_nothing(self, client: TestClient) -> None:
        looked = client.get(
            "/api/v1/budgets/joint/rates", params={"currency": "USD", "date": "2026-07-14"}
        ).json()
        assert looked == {
            "currency": "USD",
            "base": "ILS",
            "date": "2026-07-14",
            "rate": "3.7000",
            "source": "provider",
        }
        context = client.app.dependency_overrides[budget_context]()
        assert context.store.rate("USD", date(2026, 7, 14)) is None
