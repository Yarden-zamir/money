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
        )
        for commit in commits
    ]
    return HistoryPage(events=events, undoable=next((e.sha for e in events if e.mine), None))


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
    """Revert a commit, defaulting to your own most recent one.

    Scoped to your own changes: in a shared budget, silently reversing your partner's work
    from your phone is the failure worth designing against. Reverting someone else's change
    is still possible by naming its sha explicitly, which makes it a deliberate act.
    """
    commits = context.store.repo.log(limit=100)
    target = None

    if sha:
        target = next((commit for commit in commits if commit.sha.startswith(sha)), None)
    else:
        target = next(
            (commit for commit in commits if commit.trailers.get("Actor") == context.actor.login),
            None,
        )

    if target is None:
        raise not_found("a change to undo")

    try:
        new_sha = context.store.revert(target.sha, context.actor)
    except DataError as exc:
        raise ApiError("undo_conflict", str(exc), status=409) from exc

    return UndoResult(
        undone_sha=target.sha,
        undone_subject=target.subject,
        commit=new_sha,
        can_redo=True,
    )
