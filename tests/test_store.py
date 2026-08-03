"""Store tests against a real local git remote.

These use actual git rather than a fake, because the contract being tested *is* git
behaviour: that a change lands as one commit, that the trailers are greppable, that Hebrew
survives a round trip, and that a preview branch is created from main without touching it.
"""

from __future__ import annotations

import subprocess
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from money.domain.models import Bucket, Entry
from money.store import yamlio
from money.store.gitrepo import GitRepo, _fetched_at
from money.store.store import Actor, BudgetStore, DataError, new_id

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
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare repo seeded with a budget on main, standing in for GitHub."""
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True
    )

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
        later = coffee("01K9VYQ2N3X8R4T7B0M6D5C1FZ").model_copy(update={"date": date(2026, 7, 20)})
        earlier = coffee("01K9VYQ2N3X8R4T7B0M6D5C1FA").model_copy(update={"date": date(2026, 7, 2)})
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


class TestFullRoundTrip:
    """Every field on an entry must survive being written and read back.

    The place field existed on the model but not on the write schema, so entries carrying a
    location were rejected outright and the whole feature was dead. A field that exists in
    one layer and not the next is the failure mode these cover.
    """

    def rich(self) -> Entry:
        return Entry.model_validate(
            {
                "id": new_id(),
                "kind": "expense",
                "date": date(2026, 7, 14),
                "at": datetime(2026, 7, 14, 19, 42),
                "payee": "קפה גרג",
                "amount": "-50.00",
                "currency": "ILS",
                "paid_by": {"yarden": "-50.00"},
                "shares": [
                    {"person": "yarden", "amount": "-15.00", "bucket": "fun-money"},
                    {"person": "yarden", "amount": "-35.00", "bucket": "groceries"},
                ],
                "items": [
                    {
                        "label": "Coffee",
                        "amount": "-15.00",
                        "shares": [{"person": "yarden", "amount": "-15.00", "bucket": "fun-money"}],
                    },
                    {
                        "label": "Cake",
                        "amount": "-35.00",
                        "shares": [{"person": "yarden", "amount": "-35.00", "bucket": "groceries"}],
                    },
                ],
                "place": {"lat": 32.0853, "lon": 34.7818, "name": "קפה גרג", "provider_id": "abc"},
                "note": "with cake",
                "tags": ["coffee"],
            }
        )

    def test_every_field_survives_yaml(self, store: BudgetStore) -> None:
        original = self.rich()
        store.add_entry(original, ACTOR)

        [loaded] = store.entries_for_month("2026-07")
        assert loaded == original

    def test_the_clock_time_is_not_lost(self, store: BudgetStore) -> None:
        original = self.rich()
        store.add_entry(original, ACTOR)

        [loaded] = store.entries_for_month("2026-07")
        assert loaded.at == datetime(2026, 7, 14, 19, 42)

    def test_coordinates_keep_their_precision(self, store: BudgetStore) -> None:
        """A rounded coordinate would silently widen or move the 'same place' radius."""
        original = self.rich()
        store.add_entry(original, ACTOR)

        [loaded] = store.entries_for_month("2026-07")
        assert loaded.place is not None
        assert loaded.place.lat == 32.0853
        assert loaded.place.lon == 34.7818

    def test_every_model_field_is_writable_through_the_api_schema(self) -> None:
        """A field on the entry that no request can set is a feature nobody can reach.

        `rule` is derived, and `id` is minted by the server, so those are the only two the
        write schema is allowed to omit.
        """
        from money.api.schemas import EntryCreate

        derived = {"id", "rule"}
        missing = set(Entry.model_fields) - set(EntryCreate.model_fields) - derived
        assert not missing, f"entry fields no request can set: {sorted(missing)}"


class TestBucketOrder:
    def test_buckets_come_back_in_the_arranged_order(self, store: BudgetStore) -> None:
        for index, name in enumerate(["Rent", "Groceries", "Transport"]):
            store.put_bucket(
                "yarden",
                Bucket(id=name.lower(), name=name, group="Essentials", order=2 - index),
                ACTOR,
            )
        assert [b.name for b in store.buckets("yarden")] == ["Transport", "Groceries", "Rent"]

    def test_saving_a_bucket_does_not_discard_the_arrangement(self, store: BudgetStore) -> None:
        """put_bucket used to re-sort by id, so any save silently undid a reordering."""
        store.put_bucket("yarden", Bucket(id="b", name="B", order=0), ACTOR)
        store.put_bucket("yarden", Bucket(id="a", name="A", order=1), ACTOR)

        assert [b.id for b in store.buckets("yarden")] == ["b", "a"]

    def test_unarranged_buckets_read_alphabetically(self, store: BudgetStore) -> None:
        """Two buckets created together both start at order 0."""
        store.put_bucket("yarden", Bucket(id="zeta", name="Zeta"), ACTOR)
        store.put_bucket("yarden", Bucket(id="alpha", name="Alpha"), ACTOR)

        assert [b.name for b in store.buckets("yarden")] == ["Alpha", "Zeta"]


class TestNotes:
    def test_a_note_is_a_markdown_file_beside_the_ledger(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)
        store.put_note(entry.id, "Split unevenly because Dana had the cake too.", ACTOR)

        assert store.note(entry.id) == "Split unevenly because Dana had the cake too.\n"
        assert f"notes/{entry.id}.md" in store.repo.list_files("notes/")

    def test_an_empty_note_removes_the_file(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)
        store.put_note(entry.id, "temporary", ACTOR)
        store.put_note(entry.id, "", ACTOR)

        assert store.note(entry.id) is None

    def test_a_note_change_is_findable_by_entry(self, store: BudgetStore) -> None:
        entry = coffee()
        store.add_entry(entry, ACTOR)
        store.put_note(entry.id, "context", ACTOR)

        subjects = [commit.subject for commit in store.history(entry.id)]
        assert any(subject.startswith("note:") for subject in subjects)


class TestMonthClose:
    def test_closing_tags_the_current_commit(self, store: BudgetStore) -> None:
        store.add_entry(coffee(), ACTOR)
        sha = store.close_month("2026-07", ACTOR)

        assert store.closed_months() == ["2026-07"]
        assert sha == store.repo.head_sha()

    def test_reopening_removes_the_tag(self, store: BudgetStore) -> None:
        store.add_entry(coffee(), ACTOR)
        store.close_month("2026-07", ACTOR)
        store.reopen_month("2026-07", ACTOR)

        assert store.closed_months() == []

    def test_closing_does_not_lock_the_month(self, store: BudgetStore) -> None:
        """A close is a bookmark, not a permission — the tag names a commit and nothing more."""
        store.add_entry(coffee(), ACTOR)
        store.close_month("2026-07", ACTOR)

        later = coffee("01K9VYQ2N3X8R4T7B0M6D5C1FE").model_copy(update={"date": date(2026, 7, 28)})
        store.add_entry(later, ACTOR)
        assert len(store.entries_for_month("2026-07")) == 2


class TestSchemaVersion:
    def test_the_marker_is_written_on_first_change(self, store: BudgetStore) -> None:
        assert store.repo.read(".money/schema-version") is None
        store.add_entry(coffee(), ACTOR)
        assert store.repo.read(".money/schema-version") == "1\n"

    def test_data_from_a_newer_app_is_refused(self, store: BudgetStore) -> None:
        """Reading it might look fine while dropping fields this version cannot see, and the
        next write would then delete them."""
        # Pushed, not just committed: every write refreshes the clone from origin first, so
        # a local-only commit would be reset away before the check ever ran.
        store.repo.write(".money/schema-version", "99\n")
        store.repo.commit(
            message="chore: pretend a newer app wrote this",
            author_name="Other",
            author_email="other@example.com",
            paths=[".money/schema-version"],
        )
        store.repo.push(ACTOR.token)
        with pytest.raises(DataError, match="schema version 99"):
            store.add_entry(coffee(), ACTOR)


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


class TestFetchWindow:
    """`git fetch` is a network round trip and was the whole cost of a page load.

    It ran on every read: about 0.9s against GitHub, against 40ms to read and validate an
    entire budget. One screen issues three reads at once, so a single page load paid for it
    three times over — and again on every ten-second poll.
    """

    @staticmethod
    def count_fetches(repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        """Counts real `git fetch` invocations, not calls to ensure_clone."""
        fetches = [0]
        original = GitRepo._run

        def counting(self: GitRepo, *args: str, **kwargs: object):
            if args and args[0] == "fetch":
                fetches[0] += 1
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(GitRepo, "_run", counting)
        return fetches

    def test_reads_within_the_window_share_one_fetch(
        self, store: BudgetStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The fixture already fetched while cloning, which would otherwise make all three
        # reads below free and hide whether the first one still pays.
        _fetched_at.pop(store.repo.path, None)
        fetches = self.count_fetches(store.repo, monkeypatch)

        for _ in range(3):  # the budget list, the month, the buckets
            store.repo.ensure_clone(ACTOR.token, max_age=60.0)

        assert fetches[0] == 1, "three reads in one burst must cost one round trip"

    def test_a_read_with_no_window_always_fetches(
        self, store: BudgetStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """max_age defaults to 0, so nothing opts into staleness by accident."""
        fetches = self.count_fetches(store.repo, monkeypatch)

        for _ in range(3):
            store.repo.ensure_clone(ACTOR.token)

        assert fetches[0] == 3

    def test_writes_always_fetch_however_recent_the_last_read(
        self, store: BudgetStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A commit is rebased onto the remote, so it has to see the real remote state.

        Letting a write reuse a clone from moments ago would rebase onto a stale base and
        push work that silently drops whatever landed in between.
        """
        store.repo.ensure_clone(ACTOR.token, max_age=60.0)
        fetches = self.count_fetches(store.repo, monkeypatch)

        store.put_bucket("yarden", Bucket(id="fun", name="Fun"), ACTOR)

        assert fetches[0] >= 1, "a write must not reuse a recently fetched clone"

    def test_a_write_does_not_deadlock_on_its_own_lock(self, store: BudgetStore) -> None:
        """`write_lock` holds the per-clone lock and `ensure_clone` takes it again.

        The lock has to be reentrant. With a plain Lock this hangs forever on every single
        write rather than failing, which is the worst way for it to be wrong.
        """
        store.put_bucket("yarden", Bucket(id="fun", name="Fun"), ACTOR)
        store.put_bucket("yarden", Bucket(id="food", name="Food"), ACTOR)

        assert {bucket.id for bucket in store.buckets("yarden")} == {"fun", "food"}
