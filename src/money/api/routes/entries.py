"""Entry routes.

`x-cli` on a route is what gives it a first-class CLI command; see specs/cli.md. A route
without it is still reachable through `money api`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date as date_type
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from money.api.deps import BudgetContext, budget_context, person_for, writable
from money.api.errors import ApiError, not_found
from money.api.schemas import (
    CommitRef,
    EntryCreate,
    EntryList,
    EntryResponse,
    EntryUpdate,
    HistoryList,
    NoteBody,
    NoteResponse,
    PayeeSuggestion,
    ShareInput,
    SplitPreview,
)
from money.domain.amounts import ZERO
from money.domain.models import Entry, EntryKind, LineItem, Share
from money.domain.rules import first_match, shares_from_rule
from money.store.store import new_id

router = APIRouter(prefix="/budgets/{budget}/entries", tags=["entries"])


def _resolve_shares(
    context: BudgetContext, body: EntryCreate, payer: str, kind: EntryKind
) -> tuple[list[Share], str | None]:
    """Work out who bears an entry: explicit split first, then rules.

    Returns the shares and the id of the rule that produced them, which is recorded on the
    entry as an audit trail.
    """
    # Lines that carry their own split are the most specific thing the caller said, so they
    # decide the entry's split rather than being checked against a separately supplied one.
    if body.items and all(item.shares for item in body.items):
        return [
            Share(person=share.person, amount=share.amount, bucket=share.bucket or body.bucket)
            for item in body.items
            for share in (item.shares or [])
        ], None

    if body.shares:
        shares = [
            Share(person=s.person, amount=s.amount, bucket=s.bucket or body.bucket)
            for s in body.shares
        ]
        return shares, None

    rule = first_match(
        context.store.rules(),
        payee=body.payee,
        tags=body.tags,
        paid_by=payer,
        amount=body.amount,
    )
    if rule is None:
        # No rule matched and no split was given, so the payer bears the whole thing. That is
        # the behaviour a single-person budget wants and it never silently involves someone.
        return [
            Share(
                person=payer,
                amount=body.amount,
                bucket=body.bucket if kind is EntryKind.EXPENSE else None,
            )
        ], None

    shares = shares_from_rule(rule, body.amount, kind)
    if body.bucket and kind is EntryKind.EXPENSE:
        shares = [s.model_copy(update={"bucket": body.bucket}) for s in shares]
    return shares, rule.id


@router.post(
    "",
    operation_id="createEntry",
    response_model=EntryResponse,
    summary="Record an entry",
    openapi_extra={
        "x-cli": {
            "command": "entry add",
            "summary": "Record an entry",
            "args": ["amount", "payee"],
            "aliases": {"bucket": "-b", "date": "-d", "note": "-n"},
        }
    },
)
def create_entry(
    body: EntryCreate,
    context: Annotated[BudgetContext, Depends(writable)],
) -> EntryResponse:
    budget = context.store.budget()
    payer = person_for(context, context.actor.login)
    kind = body.kind

    if body.amount == ZERO:
        raise ApiError("zero_amount", "an entry must move a non-zero amount")

    paid_by = body.paid_by or {payer: body.amount}
    shares, rule_id = _resolve_shares(context, body, payer, kind)

    entry = Entry(
        id=new_id(),
        kind=kind,
        date=body.date or date_type.today(),
        payee=body.payee,
        amount=body.amount,
        currency=body.currency or budget.currency,
        paid_by=paid_by,
        shares=shares,
        note=body.note,
        tags=body.tags,
        rule=rule_id,
        items=[
            LineItem(
                label=item.label,
                amount=item.amount,
                quantity=item.quantity,
                shares=[
                    Share(person=s.person, amount=s.amount, bucket=s.bucket or body.bucket)
                    for s in (item.shares or [])
                ],
            )
            for item in (body.items or [])
        ],
    )
    sha = context.store.add_entry(entry, context.actor)
    return EntryResponse(entry=entry, commit=sha)


@router.get(
    "",
    operation_id="listEntries",
    response_model=EntryList,
    summary="List entries",
    openapi_extra={
        "x-cli": {
            "command": "entry list",
            "summary": "List entries",
            "aliases": {"month": "-m", "person": "-p", "bucket": "-b"},
        }
    },
)
def list_entries(
    context: Annotated[BudgetContext, Depends(budget_context)],
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
    person: str | None = None,
    bucket: str | None = None,
    tag: str | None = None,
    payee: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> EntryList:
    entries = context.store.entries_for_month(month) if month else context.store.all_entries()

    if person:
        entries = [e for e in entries if any(s.person == person for s in e.shares)]
    if bucket:
        entries = [e for e in entries if any(s.bucket == bucket for s in e.shares)]
    if tag:
        entries = [e for e in entries if tag in e.tags]
    if payee:
        needle = payee.casefold()
        entries = [e for e in entries if needle in e.payee.casefold()]

    entries.sort(key=lambda e: (e.date, e.id), reverse=True)
    return EntryList(entries=entries[:limit], total=len(entries))


@router.get(
    "/payees",
    operation_id="suggestPayees",
    response_model=list[PayeeSuggestion],
    summary="Payees you have used before",
    openapi_extra={"x-cli": {"command": "entry payees"}},
)
def suggest_payees(
    context: Annotated[BudgetContext, Depends(budget_context)],
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> list[PayeeSuggestion]:
    """Payees from this budget's own history, with the amount and bucket usually used.

    Typing a shop's name in full every time is the slowest part of logging an expense, and
    the answer is already in the ledger. Ranked by how recently *and* how often a payee was
    used: a shop visited weekly should beat one visited once a year, but a one-off from
    yesterday should still be reachable.
    """
    needle = q.strip().casefold()
    entries = [entry for entry in context.store.all_entries() if entry.kind is EntryKind.EXPENSE]

    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        if not needle or needle in entry.payee.casefold():
            grouped[entry.payee].append(entry)

    today = date_type.today()
    suggestions: list[tuple[float, PayeeSuggestion]] = []

    for payee, matches in grouped.items():
        matches.sort(key=lambda entry: entry.date, reverse=True)
        amount, basis = _typical_amount(matches)

        buckets = Counter(
            share.bucket for entry in matches for share in entry.shares if share.bucket
        )
        suggestion = PayeeSuggestion(
            payee=payee,
            count=len(matches),
            last_used=matches[0].date,
            amount=amount,
            bucket=buckets.most_common(1)[0][0] if buckets else None,
            basis=basis,
        )

        # Recency decays over roughly a season, so frequency wins for anything regular while
        # a recent one-off still surfaces.
        days = max(0, (today - matches[0].date).days)
        score = len(matches) * (0.5 ** (days / 90))
        suggestions.append((score, suggestion))

    suggestions.sort(key=lambda pair: -pair[0])
    return [suggestion for _, suggestion in suggestions[:limit]]


def _typical_amount(matches: list[Entry]) -> tuple[Decimal | None, str]:
    """The amount to suggest, and why.

    The most common amount when there is one — a coffee is the same price every time. When
    every visit differs, the mean is meaningless for a shop where you buy different things,
    so the most recent is shown instead.
    """
    amounts = Counter(entry.amount for entry in matches)
    most_common, seen = amounts.most_common(1)[0]
    if seen > 1:
        return most_common, "mode"
    return matches[0].amount, "latest"


@router.get("/{entry_id}", operation_id="getEntry", response_model=Entry, summary="Get one entry")
def get_entry(entry_id: str, context: Annotated[BudgetContext, Depends(budget_context)]) -> Entry:
    found = context.store.find_entry(entry_id)
    if found is None:
        raise not_found(f"entry {entry_id}")
    return found[0]


@router.patch(
    "/{entry_id}",
    operation_id="updateEntry",
    response_model=EntryResponse,
    summary="Edit an entry",
    openapi_extra={"x-cli": {"command": "entry edit", "args": ["entry_id"]}},
)
def update_entry(
    entry_id: str,
    body: EntryUpdate,
    context: Annotated[BudgetContext, Depends(writable)],
) -> EntryResponse:
    found = context.store.find_entry(entry_id)
    if found is None:
        raise not_found(f"entry {entry_id}")
    existing, month = found

    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "shares" in changes:
        changes["shares"] = [Share(**s) for s in changes["shares"]]
    if "items" in changes:
        changes["items"] = [
            LineItem(**{**item, "shares": [Share(**s) for s in (item.get("shares") or [])]})
            for item in changes["items"]
        ]

    # Rebuilding through the model re-runs the balance checks, so an edit that leaves paid_by
    # and shares disagreeing is rejected here rather than written to the ledger.
    updated = existing.model_copy(update=changes)
    updated = Entry.model_validate(updated.model_dump(mode="python"))

    sha = context.store.replace_entry(updated, previous_month=month, actor=context.actor)
    return EntryResponse(entry=updated, commit=sha)


@router.delete(
    "/{entry_id}",
    operation_id="deleteEntry",
    response_model=EntryResponse,
    summary="Delete an entry",
    openapi_extra={"x-cli": {"command": "entry delete", "args": ["entry_id"]}},
)
def delete_entry(
    entry_id: str, context: Annotated[BudgetContext, Depends(writable)]
) -> EntryResponse:
    found = context.store.find_entry(entry_id)
    if found is None:
        raise not_found(f"entry {entry_id}")
    entry, month = found

    sha = context.store.delete_entry(entry, month, context.actor)
    return EntryResponse(entry=entry, commit=sha)


@router.get(
    "/{entry_id}/history",
    operation_id="getEntryHistory",
    response_model=HistoryList,
    summary="Commits that touched this entry",
    openapi_extra={"x-cli": {"command": "entry history", "args": ["entry_id"]}},
)
def entry_history(
    entry_id: str, context: Annotated[BudgetContext, Depends(budget_context)]
) -> HistoryList:
    commits = context.store.history(entry_id)
    return HistoryList(
        commits=[
            CommitRef(sha=c.sha, subject=c.subject, author_name=c.author_name, date=c.date)
            for c in commits
        ]
    )


@router.get(
    "/{entry_id}/note",
    operation_id="getEntryNote",
    response_model=NoteResponse,
    summary="Long-form note for an entry",
    openapi_extra={"x-cli": {"command": "note show", "args": ["entry_id"]}},
)
def get_note(
    entry_id: str, context: Annotated[BudgetContext, Depends(budget_context)]
) -> NoteResponse:
    if context.store.find_entry(entry_id) is None:
        raise not_found(f"entry {entry_id}")
    return NoteResponse(entry_id=entry_id, text=context.store.note(entry_id) or "")


@router.put(
    "/{entry_id}/note",
    operation_id="putEntryNote",
    response_model=NoteResponse,
    summary="Write the long-form note for an entry",
    openapi_extra={"x-cli": {"command": "note set", "args": ["entry_id", "text"]}},
)
def put_note(
    entry_id: str,
    body: NoteBody,
    context: Annotated[BudgetContext, Depends(writable)],
) -> NoteResponse:
    """Markdown in `notes/<entry-id>.md`, so a paragraph of context diffs line by line."""
    if context.store.find_entry(entry_id) is None:
        raise not_found(f"entry {entry_id}")

    context.store.put_note(entry_id, body.text, context.actor)
    return NoteResponse(entry_id=entry_id, text=body.text)


@router.post(
    "/preview",
    operation_id="previewSplit",
    response_model=SplitPreview,
    summary="Show how an entry would be split, without saving it",
    openapi_extra={"x-cli": {"command": "entry preview", "args": ["amount", "payee"]}},
)
def preview_split(
    body: EntryCreate,
    context: Annotated[BudgetContext, Depends(budget_context)],
) -> SplitPreview:
    """Answers "what will this rule do?" before anything is committed."""
    payer = person_for(context, context.actor.login)
    shares, rule_id = _resolve_shares(context, body, payer, body.kind)
    return SplitPreview(
        rule=rule_id,
        shares=[ShareInput(person=s.person, amount=s.amount, bucket=s.bucket) for s in shares],
    )
