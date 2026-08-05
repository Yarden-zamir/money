"""Budgets, envelopes, balances, and rules."""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from money.api import db
from money.api.config import Settings
from money.api.deps import (
    BudgetContext,
    CurrentUser,
    budget_context,
    current_user,
    get_session,
    get_settings,
    github_token,
    person_for,
    repo_path,
    writable,
)
from money.api.errors import ApiError, not_found
from money.api.github import GitHubError, create_repo, repo_access
from money.api.schemas import (
    AssignRequest,
    AutoAssignRequest,
    BalanceSheet,
    BudgetConnect,
    BudgetCreate,
    BudgetJoin,
    BudgetSummary,
    EntryResponse,
    MonthResponse,
    MoveRequest,
    ReorderRequest,
    SettleRequest,
)
from money.domain.amounts import ZERO, allocate
from money.domain.derive import month_view, net_positions, settle_up, shift_month
from money.domain.models import Bucket, Budget, Entry, EntryKind, Member, Share
from money.domain.starter import starter_buckets
from money.store.gitrepo import READ_MAX_AGE, GitRepo
from money.store.store import Actor, BudgetStore, DataError, new_id

router = APIRouter(tags=["budgets"])


@router.get(
    "/budgets",
    operation_id="listBudgets",
    response_model=list[BudgetSummary],
    summary="Budgets you can see",
    openapi_extra={"x-cli": {"command": "budget list", "summary": "List budgets"}},
)
def list_budgets(
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> list[BudgetSummary]:
    """Every linked budget whose repo GitHub says the caller can read.

    Budgets they cannot read are omitted, not reported as forbidden.
    """
    token = github_token(caller.user, config)
    summaries: list[BudgetSummary] = []

    for link in session.scalars(select(db.BudgetLink).order_by(db.BudgetLink.slug)):
        access = repo_access(token, link.repo)
        if not access.can_read:
            continue

        repo = GitRepo(
            path=repo_path(config.repos_dir, link.repo),
            remote=f"https://github.com/{link.repo}.git",
            branch=config.data_branch,
        )
        repo.ensure_clone(token, max_age=READ_MAX_AGE)
        budget = BudgetStore(repo).budget()

        summaries.append(
            BudgetSummary(
                slug=link.slug,
                name=budget.name,
                repo=link.repo,
                currency=budget.currency,
                branch=config.data_branch,
                members=budget.members,
                me=budget.person_for_github(caller.user.login),
                can_write=access.can_write,
            )
        )
    return summaries


@router.post(
    "/budgets",
    operation_id="connectBudget",
    response_model=BudgetSummary,
    status_code=201,
    summary="Connect a GitHub repo as a budget",
    openapi_extra={"x-cli": {"command": "budget connect", "args": ["slug", "repo"]}},
)
def connect_budget(
    body: BudgetConnect,
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> BudgetSummary:
    if session.scalar(select(db.BudgetLink).where(db.BudgetLink.slug == body.slug)):
        raise ApiError("slug_taken", f"a budget named {body.slug!r} already exists", status=409)

    token = github_token(caller.user, config)
    access = repo_access(token, body.repo)
    if not access.can_write:
        raise ApiError(
            "no_repo_access",
            f"you need push access to {body.repo} to connect it as a budget",
            status=403,
        )

    repo = GitRepo(
        path=repo_path(config.repos_dir, body.repo),
        remote=f"https://github.com/{body.repo}.git",
        branch=config.data_branch,
    )
    # Fetched fresh, unlike the read paths: someone typically pushes budget.yaml and connects
    # it seconds later, and a clone from moments ago would not have it yet. This happens once
    # per budget, so the round trip is worth paying for.
    repo.ensure_clone(token)
    budget = BudgetStore(repo).budget()  # raises if budget.yaml is missing or invalid

    session.add(db.BudgetLink(slug=body.slug, repo=body.repo, created_by=caller.user.id))
    session.commit()

    return BudgetSummary(
        slug=body.slug,
        name=budget.name,
        repo=body.repo,
        currency=budget.currency,
        branch=config.data_branch,
        members=budget.members,
        me=budget.person_for_github(caller.user.login),
        can_write=True,
    )


@router.post(
    "/budgets/create",
    operation_id="createBudget",
    response_model=BudgetSummary,
    status_code=201,
    summary="Start a new budget in a new or empty repo",
    openapi_extra={"x-cli": {"command": "budget create", "args": ["name", "repo"]}},
)
def create_budget(
    body: BudgetCreate,
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> BudgetSummary:
    """Create the repo, write the first `budget.yaml`, and link it — in one call.

    Connecting a repo assumed one already held a budget, which left someone with no budget
    at all nowhere to start: the only route in was hand-writing YAML on github.com. This is
    that missing step, and it is deliberately one call because every intermediate state
    (repo but no budget, budget but no buckets) is one the person would have to be told
    about for no reason.
    """
    if session.scalar(select(db.BudgetLink).where(db.BudgetLink.slug == body.slug)):
        raise ApiError("slug_taken", f"a budget named {body.slug!r} already exists", status=409)

    token = github_token(caller.user, config)

    # A bare name means "make me one"; owner/repo means "use this one I already have".
    if "/" in body.repo:
        full_name = body.repo
        if not repo_access(token, full_name).can_write:
            raise ApiError(
                "no_repo_access",
                f"you need push access to {full_name} to set it up as a budget",
                status=403,
            )
    else:
        try:
            full_name = create_repo(token, body.repo, description=f"Budget data for {body.name}")
        except GitHubError as exc:
            raise ApiError("github_error", str(exc), status=502) from exc

    repo = GitRepo(
        path=repo_path(config.repos_dir, full_name),
        remote=f"https://github.com/{full_name}.git",
        branch=config.data_branch,
    )
    actor = Actor(
        login=caller.user.login,
        name=caller.user.name,
        email=caller.user.email,
        token=token,
    )
    repo.ensure_clone(token)

    budget = Budget(
        name=body.name,
        currency=body.currency,
        start_month=date_type.today().strftime("%Y-%m"),
        members=[Member(person=body.person, name=body.display_name, github=caller.user.login)],
    )
    store = BudgetStore(repo)
    try:
        store.initialize(budget, body.buckets or starter_buckets(), actor)
    except DataError as exc:
        raise ApiError("already_a_budget", str(exc), status=409) from exc

    session.add(db.BudgetLink(slug=body.slug, repo=full_name, created_by=caller.user.id))
    session.commit()

    return BudgetSummary(
        slug=body.slug,
        name=budget.name,
        repo=full_name,
        currency=budget.currency,
        branch=config.data_branch,
        members=budget.members,
        me=body.person,
        can_write=True,
    )


@router.get(
    "/budgets/{budget}",
    operation_id="getBudget",
    response_model=BudgetSummary,
    summary="One budget",
)
def get_budget(
    context: Annotated[BudgetContext, Depends(budget_context)],
    config: Annotated[Settings, Depends(get_settings)],
) -> BudgetSummary:
    budget = context.store.budget()
    return BudgetSummary(
        slug=context.slug,
        name=budget.name,
        repo=context.repo,
        currency=budget.currency,
        branch=config.data_branch,
        members=budget.members,
        me=budget.person_for_github(context.actor.login),
        can_write=context.can_write,
    )


@router.get(
    "/budgets/{budget}/members",
    operation_id="listMembers",
    response_model=list[Member],
    summary="Who is in this budget",
    openapi_extra={"x-cli": {"command": "member list"}},
)
def list_members(context: Annotated[BudgetContext, Depends(budget_context)]) -> list[Member]:
    return context.store.budget().members


@router.post(
    "/budgets/{budget}/members/me",
    operation_id="joinBudget",
    response_model=BudgetSummary,
    status_code=201,
    summary="Add yourself to a budget you can push to",
    openapi_extra={"x-cli": {"command": "budget join"}},
)
def join_budget(
    body: BudgetJoin,
    context: Annotated[BudgetContext, Depends(writable)],
    config: Annotated[Settings, Depends(get_settings)],
) -> BudgetSummary:
    """Join a budget whose repo you already have push access to.

    Without this, being handed a budget repo by someone who forgot to add you to
    `budget.yaml` made every screen fail with a 403 telling you to go and edit YAML — while
    the app's own member editor sat behind the same 403. Push access is the authority the
    rest of the app already trusts to decide who may change this data; refusing to let a
    person with that access name themselves was the app contradicting itself.

    It only ever adds you. Editing anyone else stays with `putMembers`, where removing
    someone is checked against the entries that reference them.
    """
    budget = context.store.budget()
    if budget.person_for_github(context.actor.login) is not None:
        raise ApiError(
            "already_a_member",
            f"{context.actor.login} is already in this budget",
            status=409,
        )

    member = Member(person=body.person, name=body.display_name, github=context.actor.login)
    try:
        context.store.join(member, body.buckets or starter_buckets(), context.actor)
    except DataError as exc:
        raise ApiError("person_taken", str(exc), status=409) from exc

    return BudgetSummary(
        slug=context.slug,
        name=budget.name,
        repo=context.repo,
        currency=budget.currency,
        branch=config.data_branch,
        members=[*budget.members, member],
        me=member.person,
        can_write=True,
    )


@router.put(
    "/budgets/{budget}/members",
    operation_id="putMembers",
    response_model=list[Member],
    summary="Replace the member list",
    openapi_extra={"x-cli": {"command": "member set"}},
)
def put_members(
    body: list[Member],
    context: Annotated[BudgetContext, Depends(writable)],
) -> list[Member]:
    """Replaces the list wholesale, so removals are expressible and not just additions.

    Membership decides who can be assigned a share, not who can reach the budget — that is
    GitHub repo access. Someone listed here without repo access simply never signs in.
    """
    if not body:
        raise ApiError("empty_members", "a budget needs at least one member")

    people = [member.person for member in body]
    duplicates = {person for person in people if people.count(person) > 1}
    if duplicates:
        raise ApiError("duplicate_person", f"duplicate person ids: {', '.join(sorted(duplicates))}")

    # Removing someone who still carries shares would orphan those shares and silently change
    # every balance, so it is refused while any entry references them.
    referenced = {
        share.person for entry in context.store.all_entries() for share in entry.shares
    } | {person for entry in context.store.all_entries() for person in entry.paid_by}
    orphaned = referenced - set(people)
    if orphaned:
        raise ApiError(
            "person_in_use",
            f"these people still appear in entries: {', '.join(sorted(orphaned))}",
            details={"people": sorted(orphaned)},
        )

    updated = context.store.budget().model_copy(update={"members": body})
    context.store.put_members(updated, context.actor)
    return body


@router.get(
    "/budgets/{budget}/months/{month}",
    operation_id="getMonth",
    response_model=MonthResponse,
    summary="Envelope view for a month",
    openapi_extra={"x-cli": {"command": "month", "args": ["month"], "aliases": {"person": "-p"}}},
)
def get_month(
    context: Annotated[BudgetContext, Depends(budget_context)],
    month: Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    person: str | None = None,
) -> MonthResponse:
    """Buckets are shared, so this returns every funder's standing in each of them.

    `person` still decides whose ready-to-assign is reported, because income arrives to a
    person and so does the money that has not been given a job yet.
    """
    budget = context.store.budget()
    who = person or person_for(context, context.actor.login)

    view = month_view(
        person=who,
        month=month,
        start_month=budget.start_month,
        entries=context.store.all_entries(),
        buckets=context.store.buckets(),
        assignments=context.store.all_assignments(),
        people=[member.person for member in budget.members],
    )
    return MonthResponse(
        person=view.person,
        month=view.month,
        currency=budget.currency,
        ready_to_assign=view.ready_to_assign,
        income=view.income,
        assigned=view.assigned,
        buckets=view.buckets,
    )


@router.put(
    "/budgets/{budget}/months/{month}/assign",
    operation_id="assignToBucket",
    response_model=MonthResponse,
    summary="Assign money to a bucket",
    openapi_extra={"x-cli": {"command": "assign", "args": ["month", "bucket", "amount"]}},
)
def assign_to_bucket(
    context: Annotated[BudgetContext, Depends(writable)],
    month: Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    body: AssignRequest,
) -> MonthResponse:
    who = person_for(context, context.actor.login)
    if not any(b.id == body.bucket for b in context.store.buckets()):
        raise not_found(f"bucket {body.bucket!r} for {who}")

    context.store.assign(who, month, body.bucket, body.amount, context.actor)
    return get_month(context=context, month=month, person=who)


@router.post(
    "/budgets/{budget}/months/{month}/auto-assign",
    operation_id="autoAssign",
    response_model=MonthResponse,
    summary="Fund several buckets at once",
    openapi_extra={"x-cli": {"command": "assign auto", "args": ["month", "strategy"]}},
)
def auto_assign(
    context: Annotated[BudgetContext, Depends(writable)],
    month: Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    body: AutoAssignRequest,
) -> MonthResponse:
    """Assign to many buckets in one action, which is the payday case.

    Funding envelopes one at a time is the single most repeated chore in envelope budgeting.
    Three strategies cover it: top every bucket up to its target, or repeat what was assigned
    or spent last month.

    A bucket's target belongs to the household, so filling it fills it **in the bucket's split
    ratio** — four people at 25% each put in a quarter of the shortfall. Funding is otherwise
    nobody's business but their own, which is why the other two strategies stay personal: what
    *you* assigned or spent last month says nothing about what anyone else did.

    This deliberately does not stop when the money runs out. Any funder's ready-to-assign is
    allowed to go negative, and the month view says so — refusing would leave the plan
    half-applied and harder to reason about than an overcommitment you can see.
    """
    who = person_for(context, context.actor.login)
    previous = shift_month(month, -1)
    budget = context.store.budget()
    people = [member.person for member in budget.members]

    buckets = {bucket.id: bucket for bucket in context.store.buckets() if not bucket.archived}
    wanted = set(body.buckets) if body.buckets else set(buckets)
    unknown = wanted - set(buckets)
    if unknown:
        raise not_found(f"buckets {', '.join(sorted(unknown))}")

    everyone = context.store.all_assignments()
    entries = context.store.all_entries()

    if body.strategy == "underfunded":
        funding = _fill_to_target(
            wanted=wanted, buckets=buckets, assignments=everyone, month=month, people=people
        )
    else:
        mine = everyone.get(who, {})
        funding = {
            who: _auto_assign_amounts(
                strategy=body.strategy,
                wanted=wanted,
                previous_assigned=mine.get(previous, {}),
                entries=entries,
                previous_month=previous,
                person=who,
            )
        }

    # One commit for the whole payday, not one per envelope or per person.
    changed = {
        person: {
            bucket_id: amount
            for bucket_id, amount in sorted(amounts.items())
            if amount != everyone.get(person, {}).get(month, {}).get(bucket_id, ZERO)
        }
        for person, amounts in funding.items()
    }
    changed = {person: amounts for person, amounts in changed.items() if amounts}
    if changed:
        context.store.assign_across(changed, month, context.actor)

    return get_month(context=context, month=month, person=who)


def _fill_to_target(
    *,
    wanted: set[str],
    buckets: dict[str, Bucket],
    assignments: dict[str, dict[str, dict[str, Decimal]]],
    month: str,
    people: list[str],
) -> dict[str, dict[str, Decimal]]:
    """Top every targeted bucket up to its target, shared out in the bucket's split ratio.

    A target is what the *household* means to put into a category, so the shortfall is what
    the household is short — and it is covered in the proportions everybody already agreed
    bear its spending. Four people at 25% each cover a quarter.

    Only the shortfall is shared out, not the target: someone who has already funded their
    part should not be asked again because somebody else has not. That does mean a person who
    over-funded subsidises the split of what remains, which is the same thing as agreeing to
    cover a quarter of the category.

    Nobody's funding is ever reduced. Someone who deliberately over-assigned should not have
    it silently clawed back by a button labelled "fund".
    """
    funding: dict[str, dict[str, Decimal]] = {person: {} for person in people}

    for bucket_id in sorted(wanted):
        bucket = buckets[bucket_id]
        target = bucket.target.amount if bucket.target and bucket.target.amount else None
        if target is None:
            continue  # nothing to top up towards

        held = {
            person: assignments.get(person, {}).get(month, {}).get(bucket_id, ZERO)
            for person in people
        }
        shortfall = target - sum(held.values(), start=ZERO)
        if shortfall <= ZERO:
            continue  # already funded, by whoever

        # allocate() distributes the remainder rather than rounding each share on its own, so
        # three people covering 10.00 put in 3.34/3.33/3.33 and the target is actually met.
        split = bucket.split_for(people)
        for person, extra in allocate(shortfall, split).items():
            if extra != ZERO:
                funding[person][bucket_id] = held.get(person, ZERO) + extra

    return {person: amounts for person, amounts in funding.items() if amounts}


def _auto_assign_amounts(
    *,
    strategy: str,
    wanted: set[str],
    previous_assigned: dict[str, Decimal],
    entries: list[Entry],
    previous_month: str,
    person: str,
) -> dict[str, Decimal]:
    """What one person should end up having assigned, under a personal strategy.

    Both of these look at what *this* person did last month, so they stay personal: nobody
    else's history says anything about what you meant to put in.
    """
    result: dict[str, Decimal] = {}

    for bucket_id in wanted:
        if strategy == "assigned_last_month":
            result[bucket_id] = previous_assigned.get(bucket_id, ZERO)
        else:
            spent = sum(
                (
                    share.amount
                    for entry in entries
                    if entry.month == previous_month
                    for share in entry.shares
                    if share.person == person and share.bucket == bucket_id
                ),
                start=ZERO,
            )
            result[bucket_id] = abs(spent)

    return result


@router.post(
    "/budgets/{budget}/months/{month}/move",
    operation_id="moveMoney",
    response_model=MonthResponse,
    summary="Move money from one bucket to another",
    openapi_extra={
        "x-cli": {"command": "assign move", "args": ["month", "source", "target", "amount"]}
    },
)
def move_money(
    context: Annotated[BudgetContext, Depends(writable)],
    month: Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    body: MoveRequest,
) -> MonthResponse:
    """Take from one envelope and give to another, in one action.

    Covering an overspend by editing two assignment figures means doing the arithmetic
    yourself and leaving the budget briefly wrong between the two saves. This does both sides
    together and refuses to move more than the source actually holds.
    """
    who = person_for(context, context.actor.login)
    if body.source == body.target:
        raise ApiError("same_bucket", "pick two different buckets")

    known = {bucket.id for bucket in context.store.buckets()}
    for bucket_id in (body.source, body.target):
        if bucket_id not in known:
            raise not_found(f"bucket {bucket_id!r}")

    view = get_month(context=context, month=month, person=who)
    available = {bucket.bucket: Decimal(str(bucket.available)) for bucket in view.buckets}
    if available.get(body.source, ZERO) < body.amount:
        raise ApiError(
            "not_enough_available",
            f"{body.source} only has {available.get(body.source, ZERO):.2f} available",
            details={"available": f"{available.get(body.source, ZERO):.2f}"},
        )

    # Both sides in one commit. Two commits left the budget genuinely wrong in between —
    # money taken from one envelope and not yet in the other — which is exactly what this
    # endpoint exists to avoid, and it was observable to anyone reading the repo.
    assigned = context.store.assignments(who).get(month, {})
    context.store.assign_many(
        who,
        month,
        {
            body.source: assigned.get(body.source, ZERO) - body.amount,
            body.target: assigned.get(body.target, ZERO) + body.amount,
        },
        context.actor,
    )
    return get_month(context=context, month=month, person=who)


@router.put(
    "/budgets/{budget}/buckets/order",
    operation_id="reorderBuckets",
    response_model=list[Bucket],
    summary="Move buckets into a new order, in one commit",
    openapi_extra={"x-cli": {"command": "bucket reorder"}},
)
def reorder_buckets(
    body: ReorderRequest,
    context: Annotated[BudgetContext, Depends(writable)],
) -> list[Bucket]:
    """One drag, one commit.

    A drag can shift every bucket it passes, and they all live in one file — so doing it a
    bucket at a time meant N requests, each a full fetch, commit and push, all rewriting the
    same file. Beyond being slow, it made the reorder non-atomic: a failure partway left a
    half-applied order, and the intermediate states were briefly visible to anyone else.

    It cannot create, delete, rename or retarget a bucket. Position is the only thing a drag
    means, and a wholesale replace would let a client holding a stale list undo somebody
    else's rename in passing.
    """
    person_for(context, context.actor.login)  # membership gates the write; buckets are shared
    try:
        context.store.reorder_buckets(
            [(item.bucket, item.group) for item in body.order], context.actor
        )
    except DataError as exc:
        raise not_found(str(exc)) from exc

    return context.store.buckets()


@router.put(
    "/budgets/{budget}/buckets/{bucket_id}",
    operation_id="putBucket",
    response_model=Bucket,
    summary="Create or update one of your buckets",
    openapi_extra={"x-cli": {"command": "bucket set", "args": ["bucket_id", "name"]}},
)
def put_bucket(
    bucket_id: str,
    body: Bucket,
    context: Annotated[BudgetContext, Depends(writable)],
) -> Bucket:
    if body.id != bucket_id:
        raise ApiError("id_mismatch", f"body id {body.id!r} does not match path {bucket_id!r}")

    person_for(context, context.actor.login)  # membership gates the write; buckets are shared
    context.store.put_bucket(body, context.actor)
    return body


@router.get(
    "/budgets/{budget}/buckets",
    operation_id="listBuckets",
    response_model=list[Bucket],
    summary="Every bucket in the budget",
    openapi_extra={"x-cli": {"command": "bucket list"}},
)
def list_buckets(
    context: Annotated[BudgetContext, Depends(budget_context)],
) -> list[Bucket]:
    """Buckets are shared, so this no longer takes a person.

    Each one carries the split that decides who bears its spending; how much any individual
    has put in lives in the month view, not here.
    """
    return context.store.buckets()


@router.get(
    "/budgets/{budget}/balances",
    operation_id="getBalances",
    response_model=BalanceSheet,
    summary="Who owes whom",
    openapi_extra={"x-cli": {"command": "balance", "summary": "Show who owes whom"}},
)
def get_balances(context: Annotated[BudgetContext, Depends(budget_context)]) -> BalanceSheet:
    budget = context.store.budget()
    balances = net_positions(context.store.all_entries(), [m.person for m in budget.members])
    return BalanceSheet(currency=budget.currency, balances=balances, settle_up=settle_up(balances))


@router.post(
    "/budgets/{budget}/settle",
    operation_id="settleUp",
    response_model=EntryResponse,
    summary="Record a payment between two people",
    openapi_extra={"x-cli": {"command": "settle", "args": ["to", "amount"]}},
)
def settle(
    body: SettleRequest,
    context: Annotated[BudgetContext, Depends(writable)],
) -> EntryResponse:
    """A settlement moves both net positions and touches no envelope.

    `payer` defaults to the calling user but may name the other party. The person who is
    *owed* is usually the one holding the phone when the money arrives, and if their partner
    does not use the app nobody could otherwise record it. The caller must be one of the two
    parties, so this records payments you were involved in, not other people's.
    """
    budget = context.store.budget()
    me = person_for(context, context.actor.login)
    payer = body.payer or me

    known = {member.person for member in budget.members}
    for person in (payer, body.to):
        if person not in known:
            raise not_found(f"person {person!r}")

    if body.to == payer:
        raise ApiError("self_settlement", "you cannot settle up with yourself")
    if me not in (payer, body.to):
        raise ApiError(
            "not_a_party", "you can only record a settlement you were part of", status=403
        )

    entry = Entry(
        id=new_id(),
        kind=EntryKind.SETTLEMENT,
        date=body.date or date_type.today(),
        payee=f"settle up: {payer} → {body.to}",
        amount=-body.amount,
        currency=budget.currency,
        paid_by={payer: -body.amount},
        shares=[Share(person=body.to, amount=-body.amount, bucket=None)],
        note=body.note,
    )
    sha = context.store.add_entry(entry, context.actor)
    return EntryResponse(entry=entry, commit=sha)
