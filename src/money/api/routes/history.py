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
from money.api.schemas import (
    HistoryDetail,
    HistoryEvent,
    HistoryFileChange,
    HistoryPage,
    UndoResult,
)
from money.store.gitrepo import GitError
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
    "comment:": "comment",
    "attachment:": "attachment",
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


@router.get(
    "/{sha}",
    operation_id="getHistoryDetail",
    response_model=HistoryDetail,
    summary="What one change actually did",
    openapi_extra={"x-cli": {"command": "history show", "args": ["sha"]}},
)
def get_history_detail(
    sha: str,
    context: Annotated[BudgetContext, Depends(budget_context)],
) -> HistoryDetail:
    """The diff, so "what did this change" has an answer that is not a guess.

    A subject line names what someone meant to do. The patch is what actually happened, and
    for a data model stored as YAML it reads well enough to be the answer rather than a
    debugging aid — an assignment is one number changing on one line.

    Whether it can still be undone is answered here rather than left to the client, because
    it needs the whole log: a change that something later reverted is no longer applied, and
    offering to undo it again would revert the revert.
    """
    commits = context.store.repo.log(limit=500)
    target = next((commit for commit in commits if commit.sha.startswith(sha)), None)
    if target is None:
        raise not_found(f"commit {sha}")

    reverted_by = next(
        (c.sha for c in commits if c.trailers.get("Reverts", "").startswith(target.sha[:40])),
        None,
    )

    try:
        files = context.store.repo.changed_files(target.sha)
        diff, truncated = context.store.repo.diff(target.sha)
    except GitError as exc:  # a tag or a commit with no parent has nothing to diff against
        raise ApiError("no_diff", f"cannot read the change in {sha}: {exc}", status=409) from exc

    return HistoryDetail(
        sha=target.sha,
        subject=target.subject,
        kind=_kind_of(target.subject),
        author=target.author_name,
        actor=target.trailers.get("Actor"),
        date=target.date,
        entry_id=target.trailers.get("Entry-Id"),
        person=target.trailers.get("Person"),
        month=target.trailers.get("Month"),
        mine=target.trailers.get("Actor") == context.actor.login,
        reverts=target.trailers.get("Reverts"),
        reverted_by=reverted_by,
        files=[
            HistoryFileChange(path=path, status=status, added=added, removed=removed)
            for path, status, added, removed in files
        ],
        diff=diff,
        diff_truncated=truncated,
        can_undo=context.can_write and reverted_by is None,
    )


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
