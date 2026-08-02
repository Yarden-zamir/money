"""History, undo and redo.

All of it is git. Undo records the inverse of a commit as a new commit rather than rewriting
history, so an undo is itself auditable and can be undone in turn — which is what redo is.

Assignment changes appear here alongside entries. They are events in the same ledger even
though they live in different files, and a person looking for "what changed" does not care
which file it landed in.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from money.api.deps import BudgetContext, budget_context, writable
from money.api.errors import ApiError, not_found
from money.api.schemas import HistoryEvent, HistoryPage, UndoResult
from money.store.store import DataError

router = APIRouter(prefix="/budgets/{budget}/history", tags=["history"])

# Which commit subjects map to which kind of event, for the history feed.
KINDS = {
    "entry:": "entry",
    "assign:": "assignment",
    "bucket:": "bucket",
    "rules:": "rules",
    "members:": "members",
    "note:": "note",
    "scheduled:": "scheduled",
    "revert": "undo",
}


def _kind_of(subject: str) -> str:
    for prefix, kind in KINDS.items():
        if subject.startswith(prefix):
            return kind
    return "other"


def _undo_state(commits: list, me: str) -> tuple[str | None, str | None]:
    """What undo and redo would act on, replayed from the commits themselves.

    No stored stack: a revert records which commit it reverted, so the state is recoverable
    from history alone — it survives a restart, is identical on every device, and cannot
    drift from what the repo says.

    Replaying is necessary rather than fussy. "Is the newest commit a revert" is not enough,
    because reverting a *redo* is an undo, not another redo; without tracking which is which,
    pressing redo twice would silently undo the change it had just restored.

    Two stacks, exactly as an editor keeps them:

    - a normal change pushes onto `applied` and clears `redo`, because a new edit discards
      anything that was waiting to be re-applied;
    - an undo moves an entry from `applied` to `redo`;
    - a redo moves it back.

    Each entry remembers which commit currently carries its effect, since after a redo that
    is the re-applying commit and no longer the original.
    """
    mine = [commit for commit in commits if commit.trailers.get("Actor") == me]

    applied: list[tuple[str, str]] = []  # (original sha, sha currently carrying its effect)
    redo: list[tuple[str, str]] = []  # (original sha, sha of the undo that removed it)

    for commit in reversed(mine):  # oldest first
        reverted = commit.trailers.get("Reverts")

        if not reverted:
            applied.append((commit.sha, commit.sha))
            redo.clear()
            continue

        if redo and redo[-1][1] == reverted:
            original, _ = redo.pop()
            applied.append((original, commit.sha))
            continue

        for index in range(len(applied) - 1, -1, -1):
            if applied[index][1] == reverted:
                original, _ = applied.pop(index)
                redo.append((original, commit.sha))
                break

    return (applied[-1][1] if applied else None, redo[-1][1] if redo else None)


@router.get(
    "",
    operation_id="getHistory",
    response_model=HistoryPage,
    summary="Everything that has changed, newest first",
    openapi_extra={"x-cli": {"command": "history"}},
)
def get_history(
    context: Annotated[BudgetContext, Depends(budget_context)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryPage:
    """One feed for every change, whichever file it touched.

    Assignments show up next to entries because they are the same kind of event to the person
    reading — money moved — even though one lives in a ledger file and the other in a map.
    """
    commits = context.store.repo.log(limit=limit)
    me = context.actor.login
    undoable, redoable = _undo_state(commits, me)

    events = [
        HistoryEvent(
            sha=commit.sha,
            subject=commit.subject,
            kind=_kind_of(commit.subject),
            author=commit.author_name,
            actor=commit.trailers.get("Actor"),
            date=commit.date,
            entry_id=commit.trailers.get("Entry-Id"),
            mine=commit.trailers.get("Actor") == me,
            reverts=commit.trailers.get("Reverts"),
        )
        for commit in commits
    ]
    return HistoryPage(events=events, undoable=undoable, redoable=redoable)


@router.post(
    "/undo",
    operation_id="undoChange",
    response_model=UndoResult,
    summary="Undo a change you made",
    openapi_extra={"x-cli": {"command": "undo"}},
)
def undo(
    context: Annotated[BudgetContext, Depends(writable)],
    sha: str | None = None,
) -> UndoResult:
    """Revert a change, defaulting to your most recent un-reverted one.

    Scoped to your own changes: in a shared budget, silently reversing your partner's work
    from your phone is the failure worth designing against. Naming a sha reverts anyone's,
    which makes doing so deliberate.
    """
    return _apply_revert(context, sha, want="undo")


@router.post(
    "/redo",
    operation_id="redoChange",
    response_model=UndoResult,
    summary="Re-apply something you undid",
    openapi_extra={"x-cli": {"command": "redo"}},
)
def redo(context: Annotated[BudgetContext, Depends(writable)]) -> UndoResult:
    """Re-apply the change your last undo reversed, by reverting the revert.

    Only available while the undo is still your most recent change. Anything done afterwards
    clears it, the way a new edit clears an editor's redo stack — re-applying a change on top
    of later work would produce a state nobody asked for.
    """
    return _apply_revert(context, None, want="redo")


def _apply_revert(context: BudgetContext, sha: str | None, *, want: str) -> UndoResult:
    commits = context.store.repo.log(limit=200)
    undoable, redoable = _undo_state(commits, context.actor.login)

    target_sha = sha or (undoable if want == "undo" else redoable)
    if target_sha is None:
        raise not_found("a change to undo" if want == "undo" else "anything to re-apply")

    target = next((commit for commit in commits if commit.sha.startswith(target_sha)), None)
    if target is None:
        raise not_found(f"commit {target_sha}")

    try:
        new_sha = context.store.revert(target.sha, context.actor)
    except DataError as exc:
        raise ApiError("undo_conflict", str(exc), status=409) from exc

    # After a redo the thing that was re-applied is the original, not the revert we inverted;
    # naming the revert in the confirmation would be technically true and useless.
    described = target.subject
    if want == "redo":
        original = next((c for c in commits if c.sha == target.trailers.get("Reverts")), None)
        described = original.subject if original else target.subject

    return UndoResult(
        undone_sha=target.sha,
        undone_subject=described,
        commit=new_sha,
        can_redo=want == "undo",
    )
