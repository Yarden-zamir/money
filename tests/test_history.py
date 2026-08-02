"""What history says a change did, and what it lets you do about it.

The subject line is the only description most changes ever get, and it is written once, into
git, at the moment of the write. If it does not say what happened then, nothing later can
recover it — so these tests pin the descriptions rather than the mechanism.
"""

from __future__ import annotations

import pytest

from money.domain.models import Bucket, Target
from money.store.store import describe_bucket_change, describe_list_change


class TestDescribingABucketChange:
    """`put_bucket` replaces the whole bucket, so only a comparison knows what changed."""

    def test_a_new_bucket_is_a_creation(self) -> None:
        assert describe_bucket_change(None, Bucket(id="fun", name="Fun money")) == (
            "create Fun money"
        )

    def test_a_rename_names_both_sides(self) -> None:
        before = Bucket(id="fun", name="Fun money")
        after = Bucket(id="fun", name="Bilui")
        assert describe_bucket_change(before, after) == "rename Fun money → Bilui"

    def test_moving_groups_says_where_to(self) -> None:
        before = Bucket(id="fun", name="Fun", group="Lifestyle")
        after = Bucket(id="fun", name="Fun", group="Goals")
        assert describe_bucket_change(before, after) == "move Fun to Goals"

    def test_leaving_a_group_is_not_reported_as_an_empty_name(self) -> None:
        before = Bucket(id="fun", name="Fun", group="Goals")
        after = Bucket(id="fun", name="Fun", group=None)
        assert describe_bucket_change(before, after) == "move Fun to no group"

    def test_a_target_is_spelled_out(self) -> None:
        before = Bucket(id="fun", name="Fun")
        after = Bucket(id="fun", name="Fun", target=Target(kind="monthly", amount="500"))
        assert describe_bucket_change(before, after) == "target Fun 500.00/month"

    def test_several_changes_at_once_are_all_reported(self) -> None:
        """Renaming while dragging into another group is one write, and both halves matter."""
        before = Bucket(id="fun", name="Fun", group="Lifestyle")
        after = Bucket(id="fun", name="Bilui", group="Goals")
        assert describe_bucket_change(before, after) == "rename Fun → Bilui, move Bilui to Goals"

    def test_a_drag_within_a_group_is_a_reorder(self) -> None:
        before = Bucket(id="fun", name="Fun", order=0)
        after = Bucket(id="fun", name="Fun", order=3)
        assert describe_bucket_change(before, after) == "reorder Fun"

    def test_reordering_is_not_mentioned_when_something_realer_changed(self) -> None:
        """A drag between groups changes the order of everything it passes. Saying "reorder"
        alongside "move" is noise on the one row where the move is the point."""
        before = Bucket(id="fun", name="Fun", group="A", order=0)
        after = Bucket(id="fun", name="Fun", group="B", order=2)
        assert describe_bucket_change(before, after) == "move Fun to B"


class TestDescribingAListChange:
    def test_additions_are_named(self) -> None:
        assert describe_list_change(["a"], ["a", "b"], "split rule") == ("2 split rules (added b)")

    def test_removals_are_named(self) -> None:
        assert describe_list_change(["a", "b"], ["a"], "member") == "1 member (removed b)"

    def test_both_at_once(self) -> None:
        assert describe_list_change(["a"], ["b"], "member") == "1 member (added b; removed a)"

    def test_a_reorder_is_distinguished_from_an_edit(self) -> None:
        """Same names, different order — the only signal that anything happened at all."""
        assert describe_list_change(["a", "b"], ["b", "a"], "member") == "2 members (reordered)"

    def test_editing_in_place_is_reported_as_an_edit(self) -> None:
        assert describe_list_change(["a"], ["a"], "split rule") == "1 split rule (edited)"

    def test_one_item_is_singular(self) -> None:
        assert describe_list_change([], ["a"], "recurring entry") == ("1 recurring entry (added a)")


class TestHistoryDetail:
    def test_it_returns_the_patch_and_what_changed(self, client) -> None:
        response = client.post(
            "/api/v1/budgets/joint/entries", json={"amount": "-52.30", "payee": "Cafe"}
        )
        sha = response.json()["commit"]

        detail = client.get(f"/api/v1/budgets/joint/history/{sha}")
        assert detail.status_code == 200, detail.text
        body = detail.json()

        assert body["kind"] == "entry"
        assert body["mine"] is True
        assert body["can_undo"] is True
        # The very first write also stamps .money/schema-version, so this asserts the ledger
        # file is among the changes rather than that it is the only one.
        ledger = next(file for file in body["files"] if file["path"].startswith("ledger/"))
        assert ledger["status"] == "added"
        assert ledger["added"] > 0
        assert "Cafe" in body["diff"]

    def test_an_undone_change_can_no_longer_be_undone(self, client) -> None:
        """Offering undo on something already reverted would revert the revert — which is
        redo, wearing the wrong label."""
        response = client.post(
            "/api/v1/budgets/joint/entries", json={"amount": "-52.30", "payee": "Cafe"}
        )
        sha = response.json()["commit"]
        client.post("/api/v1/budgets/joint/history/undo", params={"sha": sha})

        body = client.get(f"/api/v1/budgets/joint/history/{sha}").json()
        assert body["can_undo"] is False
        assert body["reverted_by"] is not None

    def test_an_unknown_sha_is_a_404(self, client) -> None:
        response = client.get("/api/v1/budgets/joint/history/deadbeef")
        assert response.status_code == 404

    def test_undo_and_redo_are_not_matched_as_shas(self, client) -> None:
        """`/history/{sha}` is declared before them, and both live one segment down.

        They differ by method, so nothing collides today — this pins that, because a GET
        added to either would start resolving as a commit id instead.
        """
        client.post("/api/v1/budgets/joint/entries", json={"amount": "-1.00", "payee": "x"})

        # Reaches the undo handler, not the detail handler looking for a commit called "undo".
        assert client.post("/api/v1/budgets/joint/history/undo").status_code == 200
        # And the detail route does not answer for it either.
        assert client.get("/api/v1/budgets/joint/history/undo").status_code == 404


@pytest.fixture
def client(tmp_path, monkeypatch):
    from tests.test_api import client as api_client

    yield from api_client.__wrapped__(tmp_path, monkeypatch)
