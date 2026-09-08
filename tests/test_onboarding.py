"""The path a brand-new user takes, from no budget at all to a recorded expense.

Every case here was a dead end at some point: there was no way to create a budget, being
handed someone else's repo made every screen 403, and the first expense in a fresh budget
failed on a domain validator. They are grouped together because they are one journey — a
regression in any of them puts the app back to being unusable by someone who does not
already know how it stores data.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from money.api.app import create_app
from money.api.deps import BudgetContext, budget_context, writable
from money.domain.models import Bucket, Budget, Member
from money.domain.starter import starter_buckets
from money.store.gitrepo import GitRepo
from money.store.store import Actor, BudgetStore, DataError

# A budget that exists and does *not* list the signed-in account — what you see the first
# time someone shares their budget repo with you.
OTHERS_BUDGET = """\
name: joint
currency: ILS
start_month: 2026-07
members:
  - person: dana
    name: Dana
    github: dana-example
"""

# The household's existing envelopes — deliberately NOT the starter set, so a join that
# overwrites them with defaults is caught rather than invisible.
OTHERS_BUCKETS = """\
- id: opera
  name: Opera tickets
  group: Culture
  target: {kind: monthly, amount: '750.00'}
  split: {dana: 1}
"""


def seed_remote(tmp_path: Path, budget_yaml: str | None) -> GitRepo:
    """A git remote holding `budget_yaml`, or an empty initialized repo when it is None."""
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True
    )
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True)
    # An empty repo has no branch to clone, so seed a file either way — GitHub's `auto_init`
    # does the same thing for repos the app creates.
    (seed / "README.md").write_text("# budget\n", encoding="utf-8")
    if budget_yaml is not None:
        (seed / "budget.yaml").write_text(budget_yaml, encoding="utf-8")
        (seed / "buckets.yaml").write_text(OTHERS_BUCKETS, encoding="utf-8")
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
    return repo


ACTOR = Actor(login="dev", name="Dev User", email="dev@localhost", token="")


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget_yaml: str | None):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "var"))

    from money.api.config import settings

    settings.cache_clear()
    store = BudgetStore(seed_remote(tmp_path, budget_yaml))
    context = BudgetContext(
        slug="joint",
        repo="Yarden-zamir/budget-joint",
        store=store,
        actor=ACTOR,
        can_write=True,
    )
    app = create_app()
    app.dependency_overrides[budget_context] = lambda: context
    app.dependency_overrides[writable] = lambda: context
    return TestClient(app), store


@pytest.fixture
def outsider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A client signed in as someone the budget does not list."""
    client, store = make_client(tmp_path, monkeypatch, OTHERS_BUDGET)
    with client as ready:
        yield ready, store


class TestJoiningABudgetSomeoneElseMade:
    def test_the_budget_is_readable_and_reports_no_person(
        self, outsider: tuple[TestClient, BudgetStore]
    ) -> None:
        """`me` being null is how the web app tells "not a member" from "no budget".

        It has to answer 200: if reading the budget were itself forbidden, there would be no
        way to show who *is* in it, and nothing to offer joining.
        """
        client, _ = outsider
        response = client.get("/api/v1/budgets/joint")
        assert response.status_code == 200, response.text
        assert response.json()["me"] is None
        assert [m["person"] for m in response.json()["members"]] == ["dana"]

    def test_joining_leaves_the_household_buckets_alone(
        self, outsider: tuple[TestClient, BudgetStore]
    ) -> None:
        """Buckets are shared, so a joiner arrives with none — and must overwrite none.

        When join still seeded starter buckets (a holdover from per-person files), the moment
        anybody joined it replaced the household's whole list — names, targets, splits — with
        the seven defaults. The seed here is deliberately not the starter set so that exact
        regression fails loudly.
        """
        client, store = outsider
        before = [(b.id, b.name, b.split) for b in store.buckets()]
        assert before, "seed must contain household buckets for this test to mean anything"

        response = client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "yarden", "display_name": "Yarden"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["me"] == "yarden"

        assert [(b.id, b.name, b.split) for b in store.buckets()] == before

    def test_joining_leaves_everyone_else_alone(
        self, outsider: tuple[TestClient, BudgetStore]
    ) -> None:
        client, store = outsider
        client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "yarden", "display_name": "Yarden"},
        )
        assert [m.person for m in store.budget().members] == ["dana", "yarden"]

    def test_joining_twice_is_refused(self, outsider: tuple[TestClient, BudgetStore]) -> None:
        client, _ = outsider
        client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "yarden", "display_name": "Yarden"},
        )
        second = client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "other", "display_name": "Other"},
        )
        assert second.status_code == 409
        assert "already" in second.json()["error"]["message"]

    def test_taking_someone_elses_person_id_is_refused(
        self, outsider: tuple[TestClient, BudgetStore]
    ) -> None:
        client, store = outsider
        response = client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "dana", "display_name": "Not Dana"},
        )
        assert response.status_code == 409
        # Dana's own entry in budget.yaml must be untouched, not overwritten by the impostor.
        assert [(m.person, m.github) for m in store.budget().members] == [("dana", "dana-example")]


class TestTheFirstExpense:
    def test_a_fresh_member_can_record_one_immediately(
        self, outsider: tuple[TestClient, BudgetStore]
    ) -> None:
        """The whole point of seeding buckets: no setup step between joining and using it."""
        client, _ = outsider
        client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "yarden", "display_name": "Yarden"},
        )
        response = client.post(
            "/api/v1/budgets/joint/entries",
            json={"amount": "-50.00", "payee": "Coffee", "bucket": "opera"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["entry"]["shares"][0]["bucket"] == "opera"

    def test_an_expense_with_nowhere_to_go_explains_itself(
        self, outsider: tuple[TestClient, BudgetStore]
    ) -> None:
        """The message a person sees must not be pydantic's report.

        `str(ValidationError)` carries the model name, the input dump and a link to
        pydantic's docs. None of it is actionable, and the input dump echoes the whole entry
        back at whoever is reading.
        """
        client, _ = outsider
        client.post(
            "/api/v1/budgets/joint/members/me",
            json={"person": "yarden", "display_name": "Yarden"},
        )
        response = client.post(
            "/api/v1/budgets/joint/entries", json={"amount": "-50.00", "payee": "X"}
        )
        assert response.status_code == 422
        message = response.json()["error"]["message"]
        assert "an expense needs a bucket" in message
        for leak in ("errors.pydantic.dev", "input_value", "type=value_error", "For further"):
            assert leak not in message


class TestCreatingABudget:
    def test_it_writes_the_budget_and_buckets_in_one_commit(self, tmp_path: Path) -> None:
        """One commit, because a repo with a budget but no buckets is a state nobody needs
        to see and the app would otherwise have to explain."""
        store = BudgetStore(seed_remote(tmp_path, None))
        budget = Budget(
            name="Household",
            currency="ILS",
            start_month="2026-07",
            members=[Member(person="yarden", name="Yarden", github="dev")],
        )
        before = len(store.repo.log(limit=50))
        store.initialize(budget, starter_buckets(), ACTOR)

        assert len(store.repo.log(limit=50)) == before + 1
        assert store.budget().name == "Household"
        assert {b.id for b in store.buckets()} == {b.id for b in starter_buckets()}

    def test_seeded_buckets_come_back_grouped(self, tmp_path: Path) -> None:
        """Buckets are written in display order, so the file on disk matches the screen and
        someone reading the repo directly sees what the app shows."""
        store = BudgetStore(seed_remote(tmp_path, None))
        store.initialize(
            Budget(
                name="Household",
                currency="ILS",
                start_month="2026-07",
                members=[Member(person="yarden", name="Yarden", github="dev")],
            ),
            starter_buckets(),
            ACTOR,
        )
        groups = [bucket.group for bucket in store.buckets()]
        assert groups == sorted(groups), "buckets in a group must be contiguous"

    def test_it_refuses_a_repo_that_already_holds_a_budget(self, tmp_path: Path) -> None:
        """A typo in the repo name must not overwrite someone's existing ledger."""
        store = BudgetStore(seed_remote(tmp_path, OTHERS_BUDGET))
        budget = Budget(
            name="Household",
            currency="ILS",
            start_month="2026-07",
            members=[Member(person="yarden", name="Yarden", github="dev")],
        )
        with pytest.raises(DataError, match="already holds a budget"):
            store.initialize(budget, starter_buckets(), ACTOR)

        assert store.budget().name == "joint"  # untouched


class TestStarterBuckets:
    def test_they_are_valid_and_distinct(self) -> None:
        ids = [bucket.id for bucket in starter_buckets()]
        assert len(ids) == len(set(ids))

    def test_callers_cannot_mutate_the_template(self) -> None:
        """Returned by value, so one person renaming a bucket cannot change what the next
        person is seeded with."""
        first = starter_buckets()
        first[0].name = "Changed"
        assert starter_buckets()[0].name != "Changed"

    def test_none_of_them_invent_a_target(self) -> None:
        """A target is a claim about what someone intends to spend. Guessing it would put a
        number on screen that nobody chose."""
        assert all(bucket.target is None for bucket in starter_buckets())


def test_a_bucket_id_that_the_api_would_reject_cannot_be_seeded() -> None:
    """Guards the starter set against a rename that quietly breaks every new budget."""
    for bucket in starter_buckets():
        Bucket.model_validate(bucket.model_dump(mode="python"))

    with pytest.raises(ValidationError):
        Bucket(id="Not Valid", name="x")
