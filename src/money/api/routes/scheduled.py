"""Recurring entries.

Nothing here posts by itself. A recurrence produces a list of dates that are *due*; turning
one into a real entry is an explicit request, so every commit in the data repo still has a
person's name on it and no money appears in a budget while nobody is looking.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from money.api.deps import BudgetContext, budget_context, person_for, writable
from money.api.errors import ApiError, not_found
from money.api.schemas import DueEntry, DueList, EntryResponse, PostRequest
from money.domain.models import Entry, EntryKind, Scheduled, Share
from money.domain.recurrence import occurrences
from money.domain.rules import first_match, shares_from_rule
from money.store.store import new_id

router = APIRouter(prefix="/budgets/{budget}/scheduled", tags=["scheduled"])

# How far ahead "due" looks by default. A fortnight is enough to see the rent coming without
# turning the list into a forecast nobody asked for.
DEFAULT_HORIZON_DAYS = 14


@router.get(
    "",
    operation_id="listScheduled",
    response_model=list[Scheduled],
    summary="Recurring entries",
    openapi_extra={"x-cli": {"command": "scheduled list"}},
)
def list_scheduled(context: Annotated[BudgetContext, Depends(budget_context)]) -> list[Scheduled]:
    return context.store.scheduled()


@router.put(
    "",
    operation_id="putScheduled",
    response_model=list[Scheduled],
    summary="Replace the recurring entries",
    openapi_extra={"x-cli": {"command": "scheduled set"}},
)
def put_scheduled(
    body: list[Scheduled],
    context: Annotated[BudgetContext, Depends(writable)],
) -> list[Scheduled]:
    ids = [item.id for item in body]
    duplicates = {item for item in ids if ids.count(item) > 1}
    if duplicates:
        raise ApiError("duplicate_id", f"duplicate ids: {', '.join(sorted(duplicates))}")

    # last_posted is set by posting, never by an edit. Letting a save carry it would make it
    # possible to silently re-offer or skip a charge by editing the template.
    existing = {item.id: item.last_posted for item in context.store.scheduled()}
    preserved = [
        item.model_copy(update={"last_posted": existing.get(item.id, item.last_posted)})
        for item in body
    ]

    context.store.put_scheduled(preserved, context.actor)
    return preserved


@router.get(
    "/due",
    operation_id="listDue",
    response_model=DueList,
    summary="Recurring entries that are due",
    openapi_extra={"x-cli": {"command": "scheduled due"}},
)
def list_due(
    context: Annotated[BudgetContext, Depends(budget_context)],
    through: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> DueList:
    """What each recurrence owes the ledger, up to `through` (default: two weeks out).

    Dates already posted are excluded, so opening this twice never offers the same charge
    twice. A paused recurrence is skipped entirely.
    """
    horizon = (
        date_type.fromisoformat(through)
        if through
        else date_type.today() + timedelta(days=DEFAULT_HORIZON_DAYS)
    )

    due: list[DueEntry] = []
    for item in context.store.scheduled():
        if item.paused:
            continue
        limit = min(horizon, item.ends) if item.ends else horizon
        for when in occurrences(
            item.recurrence, start=item.starts, through=limit, after=item.last_posted
        ):
            due.append(
                DueEntry(
                    scheduled_id=item.id,
                    name=item.name,
                    payee=item.payee,
                    amount=item.amount,
                    currency=item.currency,
                    kind=item.kind,
                    date=when,
                    overdue=when < date_type.today(),
                )
            )

    due.sort(key=lambda item: (item.date, item.name))
    return DueList(due=due, through=horizon)


@router.post(
    "/{scheduled_id}/post",
    operation_id="postScheduled",
    response_model=EntryResponse,
    summary="Turn a due recurrence into a real entry",
    openapi_extra={"x-cli": {"command": "scheduled post", "args": ["scheduled_id", "date"]}},
)
def post_scheduled(
    scheduled_id: str,
    body: PostRequest,
    context: Annotated[BudgetContext, Depends(writable)],
) -> EntryResponse:
    """Creates the entry and records that this date was posted, in one commit.

    One commit matters: if the entry landed and the marker did not, the same charge would be
    offered again and posted twice.
    """
    budget = context.store.budget()
    item = next((one for one in context.store.scheduled() if one.id == scheduled_id), None)
    if item is None:
        raise not_found(f"scheduled entry {scheduled_id!r}")

    when = body.date or date_type.today()
    if item.last_posted and when <= item.last_posted:
        raise ApiError(
            "already_posted",
            f"{item.name} is already posted through {item.last_posted.isoformat()}",
            details={"last_posted": item.last_posted.isoformat()},
        )

    payer = person_for(context, context.actor.login)
    paid_by = item.paid_by or {payer: item.amount}
    shares = list(item.shares) or _shares_for(context, item, payer)

    entry = Entry(
        id=new_id(),
        kind=item.kind,
        date=when,
        payee=item.payee,
        amount=item.amount,
        currency=item.currency or budget.currency,
        paid_by=paid_by,
        shares=shares,
        note=item.note,
        tags=item.tags,
    )
    sha = context.store.post_scheduled(entry, scheduled_id, context.actor)
    return EntryResponse(entry=entry, commit=sha)


def _shares_for(context: BudgetContext, item: Scheduled, payer: str) -> list[Share]:
    """Fall back to the split rules when a template carries no explicit split.

    A template without a split stays correct as the rules change, which is what someone wants
    for "groceries" and not for "rent split 60/40" — so both are expressible.
    """
    rule = first_match(
        context.store.rules(),
        payee=item.payee,
        tags=item.tags,
        paid_by=payer,
        amount=item.amount,
    )
    expense = item.kind is EntryKind.EXPENSE
    if rule is None:
        return [Share(person=payer, amount=item.amount, bucket=item.bucket if expense else None)]

    shares = shares_from_rule(rule, item.amount, item.kind)
    if expense and item.bucket:
        # The template's own bucket wins over the rule's: it was chosen for this charge
        # specifically, while the rule is a default for everything that looks like it.
        shares = [share.model_copy(update={"bucket": item.bucket}) for share in shares]
    return shares
