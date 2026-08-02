"""Undo and redo.

The stack is derived from git rather than stored, so these check the derivation: that undo
walks backwards rather than repeating itself, that redo is only offered when it is safe, and
that doing something new clears it the way an editor does.
"""

from __future__ import annotations

from dataclasses import dataclass

from money.api.routes.history import _undo_state


@dataclass
class FakeCommit:
    sha: str
    subject: str
    trailers: dict[str, str]


def change(sha: str, actor: str = "me", subject: str = "entry: add x") -> FakeCommit:
    return FakeCommit(sha=sha, subject=subject, trailers={"Actor": actor})


def revert(sha: str, of: str, actor: str = "me") -> FakeCommit:
    return FakeCommit(
        sha=sha, subject=f"revert: {of[:7]}", trailers={"Actor": actor, "Reverts": of}
    )


class TestUndo:
    def test_it_targets_your_most_recent_change(self) -> None:
        commits = [change("c3"), change("c2"), change("c1")]
        undoable, redoable = _undo_state(commits, "me")
        assert undoable == "c3"
        assert redoable is None

    def test_it_skips_a_change_already_undone(self) -> None:
        """Pressing undo twice must walk backwards, not re-revert the same commit."""
        commits = [revert("r1", of="c3"), change("c3"), change("c2")]
        undoable, _ = _undo_state(commits, "me")
        assert undoable == "c2"

    def test_it_ignores_other_peoples_changes(self) -> None:
        commits = [change("c2", actor="dana"), change("c1", actor="me")]
        undoable, _ = _undo_state(commits, "me")
        assert undoable == "c1"

    def test_nothing_to_undo_is_not_an_error(self) -> None:
        assert _undo_state([change("c1", actor="dana")], "me") == (None, None)


class TestRedo:
    def test_it_is_offered_right_after_an_undo(self) -> None:
        commits = [revert("r1", of="c1"), change("c1")]
        undoable, redoable = _undo_state(commits, "me")
        assert redoable == "r1"
        assert undoable is None  # c1 is already undone

    def test_a_new_change_clears_it(self) -> None:
        """An editor's redo stack is cleared by the next edit; so is this one.

        Re-applying a change on top of later work would produce a state nobody asked for.
        """
        commits = [change("c2"), revert("r1", of="c1"), change("c1")]
        _, redoable = _undo_state(commits, "me")
        assert redoable is None

    def test_redoing_a_redo_is_not_offered_twice(self) -> None:
        """Once the revert has itself been reverted there is nothing left to re-apply."""
        commits = [revert("r2", of="r1"), revert("r1", of="c1"), change("c1")]
        _, redoable = _undo_state(commits, "me")
        assert redoable is None

    def test_undo_after_redo_takes_the_change_away_again(self) -> None:
        """r2 re-applied c1, so undo must offer to remove it — by reverting r2, not c1.

        After a redo the commit carrying the change's effect is the redo itself; reverting
        the original again would do nothing.
        """
        commits = [revert("r2", of="r1"), revert("r1", of="c1"), change("c1")]
        undoable, redoable = _undo_state(commits, "me")
        assert undoable == "r2"
        assert redoable is None

    def test_someone_elses_undo_does_not_offer_you_a_redo(self) -> None:
        commits = [revert("r1", of="c1", actor="dana"), change("c1", actor="me")]
        _, redoable = _undo_state(commits, "me")
        assert redoable is None
