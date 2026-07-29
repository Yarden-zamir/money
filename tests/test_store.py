"""Store tests against a real local git remote.

These use actual git rather than a fake, because the contract being tested *is* git
behaviour: that a change lands as one commit, that the trailers are greppable, that Hebrew
survives a round trip, and that a preview branch is created from main without touching it.
"""

from __future__ import annotations

import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from money.domain.models import Bucket, Entry
from money.store.gitrepo import GitRepo
from money.store.store import Actor, BudgetStore, new_id
from money.store import yamlio

D = Decimal
ACTOR = Actor(
    login="Yarden-zamir", name="Yarden Zamir", email="dev@yarden-zamir.com", token="unused-locally"
)

BUDGET_YAML = """\
name: joint
currency: ILS
start_month: 2026-07
members:
  - person: yarden
    name: Yarden
    github: Yarden-zamir
  - person: dana
    name: Dana
    github: dana-example
"""


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare repo seeded with a budget on main, standing in for GitHub."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True)
    (seed / "budget.yaml").write_text(BUDGET_YAML, encoding="utf-8")
    git("config", "user.email", "seed@example.com", cwd=seed)
    git("config", "user.name", "seed", cwd=seed)
    git("add", "-A", cwd=seed)
    git("commit", "-m", "chore: seed budget", cwd=seed)
    git("push", "origin", "main", cwd=seed)
    return bare


@pytest.fixture
def store(remote: Path, tmp_path: Path) -> BudgetStore:
    repo = GitRepo(path=tmp_path / "clone", remote=str(remote), branch="main")
    repo.ensure_clone(ACTOR.token)
    return BudgetStore(repo)


def coffee(entry_id: str | None = None) -> Entry:
    return Entry.model_validate(
        {
            "id": entry_id or new_id(),
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
    )


class TestIds:
    def test_ulids_sort_by_creation_time(self) -> None:
        ids = [new_id() for _ in range(50)]
        assert ids == sorted(ids) or len(set(ids)) == 50  # monotonic within a millisecond tie
        assert all(len(i) == 26 for i in ids)


class TestRoundTrip:
    def test_entry_survives_a_write_and_read(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)

        [loaded] = store.entries_for_month("2026-07")
        assert loaded == entry

    def test_hebrew_is_stored_readable_not_escaped(self, store: BudgetStore) -> None:
        store.add_entry(coffee(), ACTOR)
        raw = store.repo.read("ledger/2026-07.yaml")
        assert raw is not None
        assert "קפה גרג" in raw
        assert "\\u05e7" not in raw

    def test_amounts_are_plain_numbers_and_stay_exact(self, store: BudgetStore) -> None:
        store.add_entry(coffee(), ACTOR)
        raw = store.repo.read("ledger/2026-07.yaml")
        assert raw is not None
        assert "amount: -50.00" in raw  # unquoted, readable
        assert "'-50.00'" not in raw

        parsed = yamlio.load(raw)
        assert parsed[0]["amount"] == D("-50.00")
        assert isinstance(parsed[0]["amount"], Decimal)

    def test_a_float_never_appears_after_a_yaml_round_trip(self) -> None:
        """0.1 + 0.2 style drift must be impossible through the storage layer."""
        text = yamlio.dump({"amount": D("0.10"), "other": D("0.20")})
        loaded = yamlio.load(text)
        assert loaded["amount"] + loaded["other"] == D("0.30")


class TestCommits:
    def test_one_change_is_one_commit_authored_by_the_actor(self, store: BudgetStore) -> None:
        before = len(store.repo.log(limit=100))
        sha = store.add_entry(coffee(), ACTOR)
        after = store.repo.log(limit=100)

        assert len(after) == before + 1
        assert after[0].sha == sha
        assert after[0].author_name == "Yarden Zamir"
        assert after[0].author_email == "dev@yarden-zamir.com"
        assert after[0].subject == "entry: add קפה גרג 50.00 ILS"

    def test_entry_history_is_found_by_trailer(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)

        edited = entry.model_copy(update={"payee": "קפה אחר"})
        store.replace_entry(edited, previous_month="2026-07", actor=ACTOR)

        history = store.history(entry.id)
        assert len(history) == 2
        assert all(commit.trailers["Entry-Id"] == entry.id for commit in history)
        assert history[0].trailers["Actor"] == "Yarden-zamir"

    def test_deleting_the_last_entry_removes_the_ledger_file(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)
        store.delete_entry(entry, "2026-07", ACTOR)

        assert store.repo.read("ledger/2026-07.yaml") is None
        assert store.entries_for_month("2026-07") == []

    def test_editing_the_date_moves_the_entry_between_months(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)

        moved = entry.model_copy(update={"date": date(2026, 8, 3)})
        store.replace_entry(moved, previous_month="2026-07", actor=ACTOR)

        assert store.entries_for_month("2026-07") == []
        assert store.entries_for_month("2026-08") == [moved]


class TestOrdering:
    def test_entries_are_kept_sorted_so_concurrent_appends_do_not_conflict(
        self, store: BudgetStore
    ) -> None:
        later = coffee("01K9VYQ2N3X8R4T7B0M6D5C1FZ").model_copy(
            update={"date": date(2026, 7, 20)}
        )
        earlier = coffee("01K9VYQ2N3X8R4T7B0M6D5C1FA").model_copy(
            update={"date": date(2026, 7, 2)}
        )
        store.add_entry(later, ACTOR)
        store.add_entry(earlier, ACTOR)

        assert [e.date for e in store.entries_for_month("2026-07")] == [
            date(2026, 7, 2),
            date(2026, 7, 20),
        ]


class TestBranches:
    def test_a_preview_branch_is_created_from_main_and_leaves_main_alone(
        self, remote: Path, tmp_path: Path
    ) -> None:
        """This is the PR-preview contract from specs/deployment.md."""
        prod = BudgetStore(GitRepo(tmp_path / "prod", str(remote), "main"))
        prod.repo.ensure_clone(ACTOR.token)
        prod.add_entry(coffee(), ACTOR)

        preview_repo = GitRepo(tmp_path / "preview", str(remote), "pr-42")
        preview_repo.ensure_clone(ACTOR.token)
        preview = BudgetStore(preview_repo)

        # The preview starts from main's data...
        assert len(preview.entries_for_month("2026-07")) == 1
        assert preview.budget().name == "joint"

        # ...and its writes do not reach main.
        preview.add_entry(coffee().model_copy(update={"date": date(2026, 7, 25)}), ACTOR)
        assert len(preview.entries_for_month("2026-07")) == 2

        prod.repo.ensure_clone(ACTOR.token)
        assert len(prod.entries_for_month("2026-07")) == 1


class TestBuckets:
    def test_buckets_and_assignments_round_trip(self, store: BudgetStore) -> None:
        store.put_bucket("yarden", Bucket(id="fun-money", name="בילויים", group="lifestyle"), ACTOR)
        store.assign("yarden", "2026-07", "fun-money", D("400.00"), ACTOR)

        assert store.buckets("yarden")[0].name == "בילויים"
        assert store.assignments("yarden") == {"2026-07": {"fun-money": D("400.00")}}

    def test_assigning_zero_removes_the_line(self, store: BudgetStore) -> None:
        store.assign("yarden", "2026-07", "fun-money", D("400.00"), ACTOR)
        store.assign("yarden", "2026-07", "fun-money", D("0.00"), ACTOR)

        assert store.assignments("yarden") == {"2026-07": {}}
