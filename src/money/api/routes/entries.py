"""Entry routes.

`x-cli` on a route is what gives it a first-class CLI command; see specs/cli.md. A route
without it is still reachable through `money api`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC
from datetime import date as date_type
from datetime import datetime as datetime_type
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, Query, Response

from money.api.deps import BudgetContext, budget_context, person_for, writable
from money.api.errors import ApiError, forbidden, not_found
from money.api.schemas import (
    AttachmentList,
    AttachmentResponse,
    CommentCreate,
    CommentList,
    CommitRef,
    EntryCreate,
    EntryExtras,
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
from money.domain.models import Comment, Entry, EntryKind, LineItem, Place, Share
from money.domain.rules import first_match, shares_from_split
from money.store.store import ATTACHMENT_MAX_BYTES, ATTACHMENT_TYPES, DataError, new_id

router = APIRouter(prefix="/budgets/{budget}/entries", tags=["entries"])


def _resolve_shares(
    context: BudgetContext, body: EntryCreate, payer: str, kind: EntryKind
) -> tuple[list[Share], str | None]:
    """Work out who bears an entry.

    Order of precedence, most specific first:

    1. line-level splits on a receipt,
    2. an explicit split on the entry — the advanced override,
    3. the split of the bucket it lands in, which is the default and covers almost everything,
    4. the payer alone, when there is no bucket to ask.

    The bucket is whatever the caller named, or whatever a rule matched: a rule categorises,
    and the category decides who bears it.

    Returns the shares and the id of the rule that chose the bucket, recorded on the entry as
    an audit trail. The split is resolved **now** and stored on the entry — editing a bucket's
    split later must not rewrite who owed whom for months of history.
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

    rule = None
    bucket_id = body.bucket
    if bucket_id is None and kind is EntryKind.EXPENSE:
        rule = first_match(
            context.store.rules(),
            payee=body.payee,
            tags=body.tags,
            paid_by=payer,
            amount=body.amount,
        )
        bucket_id = rule.bucket if rule else None

    bucket = next((b for b in context.store.buckets() if b.id == bucket_id), None)
    if bucket is None:
        # Nothing to ask. The payer bears the whole thing, which is what a single-person
        # budget wants and never silently involves anybody else.
        return [
            Share(
                person=payer,
                amount=body.amount,
                bucket=bucket_id if kind is EntryKind.EXPENSE else None,
            )
        ], None

    people = [member.person for member in context.store.budget().members]
    shares = shares_from_split(bucket.split_for(people), body.amount, bucket.id, kind)
    return shares, rule.id if rule else None


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
        # Recorded even when the date was back-dated, so a time pattern reads when it
        # actually happened rather than what the accounting date claims.
        at=body.at or datetime_type.now(),
        payee=body.payee,
        amount=body.amount,
        currency=body.currency or budget.currency,
        paid_by=paid_by,
        shares=shares,
        note=body.note,
        tags=body.tags,
        rule=rule_id,
        place=Place(**body.place.model_dump()) if body.place else None,
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
    kind: EntryKind | None = None,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Free text over payee, note, tags, place and receipt lines. "
            "Every word must match somewhere.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> EntryList:
    entries = context.store.entries_for_month(month) if month else context.store.all_entries()

    if person:
        entries = [e for e in entries if any(s.person == person for s in e.shares)]
    if bucket:
        entries = [e for e in entries if any(s.bucket == bucket for s in e.shares)]
    if tag:
        entries = [e for e in entries if tag in e.tags]
    if kind:
        entries = [e for e in entries if e.kind is kind]
    if payee:
        needle = payee.casefold()
        entries = [e for e in entries if needle in e.payee.casefold()]
    if q and q.strip():
        entries = [e for e in entries if _matches(e, q)]

    entries.sort(key=lambda e: (e.date, e.id), reverse=True)
    page = entries[:limit]
    return EntryList(
        entries=page,
        total=len(entries),
        extras={
            entry_id: EntryExtras(comments=comments, attachments=attachments)
            for entry_id, (comments, attachments) in context.store.extras(
                [e.id for e in page]
            ).items()
        },
    )


def _matches(entry: Entry, query: str) -> bool:
    """Every word of the query appears somewhere on the entry.

    Words rather than the phrase, so "coffee receipt" finds a coffee whose note mentions the
    receipt. Substring rather than prefix, because Hebrew payees carry prefixes ("בקפה") that
    a word boundary would hide. Amounts and people are not searched: "50" would match every
    entry in the fifties, and a person's id is on every entry the rules split with them —
    the `person` and amount filters are the right tools for those.
    """
    haystack = " ".join(
        [
            entry.payee,
            entry.note or "",
            " ".join(entry.tags),
            entry.place.name if entry.place and entry.place.name else "",
            " ".join(item.label for item in entry.items),
        ]
    ).casefold()
    return all(word in haystack for word in query.casefold().split())


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
    if "place" in changes:
        changes["place"] = Place(**changes["place"])

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


@router.get(
    "/{entry_id}/comments",
    operation_id="listComments",
    response_model=CommentList,
    summary="The conversation under an entry",
    openapi_extra={"x-cli": {"command": "comment list", "args": ["entry_id"]}},
)
def list_comments(
    entry_id: str, context: Annotated[BudgetContext, Depends(budget_context)]
) -> CommentList:
    if context.store.find_entry(entry_id) is None:
        raise not_found(f"entry {entry_id}")
    return CommentList(entry_id=entry_id, comments=context.store.comments(entry_id))


@router.post(
    "/{entry_id}/comments",
    operation_id="addComment",
    response_model=CommentList,
    summary="Say something under an entry",
    openapi_extra={"x-cli": {"command": "comment add", "args": ["entry_id", "text"]}},
)
def add_comment(
    entry_id: str,
    body: CommentCreate,
    context: Annotated[BudgetContext, Depends(writable)],
) -> CommentList:
    """Appends and returns the whole thread, so a client can render the reply in place
    without a second round trip — the thread is short by nature."""
    if context.store.find_entry(entry_id) is None:
        raise not_found(f"entry {entry_id}")

    comment = Comment(
        id=new_id(),
        author=person_for(context, context.actor.login),
        at=datetime_type.now(UTC),
        text=body.text.strip(),
    )
    context.store.add_comment(entry_id, comment, context.actor)
    return CommentList(entry_id=entry_id, comments=context.store.comments(entry_id))


@router.delete(
    "/{entry_id}/comments/{comment_id}",
    operation_id="deleteComment",
    response_model=CommentList,
    summary="Take back something you said",
)
def delete_comment(
    entry_id: str,
    comment_id: str,
    context: Annotated[BudgetContext, Depends(writable)],
) -> CommentList:
    """Only the author. A comment is attributed speech, and removing someone else's words
    from a shared record is not an edit anybody should be able to make silently."""
    existing = next((c for c in context.store.comments(entry_id) if c.id == comment_id), None)
    if existing is None:
        raise not_found(f"comment {comment_id}")
    if existing.author != person_for(context, context.actor.login):
        raise forbidden("only the person who wrote a comment can remove it")

    context.store.delete_comment(entry_id, comment_id, context.actor)
    return CommentList(entry_id=entry_id, comments=context.store.comments(entry_id))


@router.get(
    "/{entry_id}/attachments",
    operation_id="listAttachments",
    response_model=AttachmentList,
    summary="Files kept beside an entry",
    openapi_extra={"x-cli": {"command": "attachment list", "args": ["entry_id"]}},
)
def list_attachments(
    entry_id: str, context: Annotated[BudgetContext, Depends(budget_context)]
) -> AttachmentList:
    if context.store.find_entry(entry_id) is None:
        raise not_found(f"entry {entry_id}")
    return AttachmentList(
        entry_id=entry_id,
        attachments=[
            AttachmentResponse(name=a.name, size=a.size, content_type=a.content_type)
            for a in context.store.attachments(entry_id)
        ],
    )


@router.post(
    "/{entry_id}/attachments",
    operation_id="addAttachment",
    response_model=AttachmentList,
    summary="Attach a receipt photo or PDF",
)
def add_attachment(
    entry_id: str,
    context: Annotated[BudgetContext, Depends(writable)],
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
    content_type: Annotated[str | None, Header()] = None,
    media_type: Annotated[
        str | None,
        Query(description="The file's type when the Content-Type header cannot carry it"),
    ] = None,
) -> AttachmentList:
    """The body is the file itself.

    Raw bytes rather than multipart: there is exactly one file per request, so a multipart
    envelope would add a parser dependency and a field name for nothing. The type comes from
    the Content-Type header when it names one we accept, else from `media_type` — a
    generated client sends the schema's octet-stream header and cannot say more.
    """
    if context.store.find_entry(entry_id) is None:
        raise not_found(f"entry {entry_id}")

    from_header = (content_type or "").split(";")[0].strip().lower()
    media = from_header if from_header in ATTACHMENT_TYPES else (media_type or "").lower()
    extension = ATTACHMENT_TYPES.get(media)
    if extension is None:
        raise ApiError(
            "unsupported_attachment",
            f"{media or from_header or 'unknown'} is not a supported attachment type",
            details={"supported": sorted(ATTACHMENT_TYPES)},
        )
    if len(data) > ATTACHMENT_MAX_BYTES:
        raise ApiError(
            "attachment_too_large",
            f"attachments are limited to {ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB",
            status=413,
        )

    try:
        context.store.add_attachment(entry_id, new_id() + extension, media, data, context.actor)
    except DataError as exc:
        raise ApiError("invalid_attachment", str(exc)) from exc
    return list_attachments(entry_id, context)


@router.get(
    "/{entry_id}/attachments/{name}",
    operation_id="getAttachment",
    summary="The file itself",
    response_class=Response,
    responses={200: {"content": {media: {} for media in ATTACHMENT_TYPES}}},
)
def get_attachment(
    entry_id: str, name: str, context: Annotated[BudgetContext, Depends(budget_context)]
) -> Response:
    data = context.store.attachment(entry_id, name)
    if data is None:
        raise not_found(f"attachment {name}")
    media = next(
        (ct for ct, ext in ATTACHMENT_TYPES.items() if name.endswith(ext)),
        "application/octet-stream",
    )
    # Immutable: the name is a ULID, so the same URL never serves different bytes. A browser
    # may keep a receipt photo for as long as it likes.
    return Response(
        content=data,
        media_type=media,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete(
    "/{entry_id}/attachments/{name}",
    operation_id="deleteAttachment",
    response_model=AttachmentList,
    summary="Remove a file from an entry",
)
def delete_attachment(
    entry_id: str, name: str, context: Annotated[BudgetContext, Depends(writable)]
) -> AttachmentList:
    try:
        context.store.delete_attachment(entry_id, name, context.actor)
    except DataError as exc:
        raise not_found(str(exc)) from exc
    return list_attachments(entry_id, context)


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
