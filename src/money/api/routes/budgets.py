"""Budgets, envelopes, balances, and rules."""

from __future__ import annotations

from datetime import date as date_type
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
from money.api.github import repo_access
from money.api.schemas import (
    AssignRequest,
    BalanceSheet,
    BudgetConnect,
    BudgetSummary,
    EntryResponse,
    MonthResponse,
    SettleRequest,
)

from money.domain.derive import month_view, net_positions, settle_up
from money.domain.models import Bucket, Entry, EntryKind, Share
from money.store.gitrepo import GitRepo
from money.store.store import BudgetStore, new_id

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
        repo.ensure_clone(token)
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
    "/budgets/{budget}/months/{month}",
    operation_id="getMonth",
    response_model=MonthResponse,
    summary="Envelope view for a month",
    openapi_extra={
        "x-cli": {"command": "month", "args": ["month"], "aliases": {"person": "-p"}}
    },
)
def get_month(
    context: Annotated[BudgetContext, Depends(budget_context)],
    month: Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    person: str | None = None,
) -> MonthResponse:
    """Defaults to the calling user's own envelopes, since buckets are per person."""
    budget = context.store.budget()
    who = person or person_for(context, context.actor.login)

    view = month_view(
        person=who,
        month=month,
        start_month=budget.start_month,
        entries=context.store.all_entries(),
        buckets=context.store.buckets(who),
        assignments=context.store.assignments(who),
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
    openapi_extra={
        "x-cli": {"command": "assign", "args": ["month", "bucket", "amount"]}
    },
)
def assign_to_bucket(
    context: Annotated[BudgetContext, Depends(writable)],
    month: Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    body: AssignRequest,
) -> MonthResponse:
    who = person_for(context, context.actor.login)
    if not any(b.id == body.bucket for b in context.store.buckets(who)):
        raise not_found(f"bucket {body.bucket!r} for {who}")

    context.store.assign(who, month, body.bucket, body.amount, context.actor)
    return get_month(context=context, month=month, person=who)


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

    who = person_for(context, context.actor.login)
    context.store.put_bucket(who, body, context.actor)
    return body


@router.get(
    "/budgets/{budget}/buckets",
    operation_id="listBuckets",
    response_model=list[Bucket],
    summary="Buckets for a person",
    openapi_extra={"x-cli": {"command": "bucket list", "aliases": {"person": "-p"}}},
)
def list_buckets(
    context: Annotated[BudgetContext, Depends(budget_context)],
    person: str | None = None,
) -> list[Bucket]:
    who = person or person_for(context, context.actor.login)
    return context.store.buckets(who)


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
    return BalanceSheet(
        currency=budget.currency, balances=balances, settle_up=settle_up(balances)
    )


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
    """A settlement moves both net positions and touches no envelope."""
    budget = context.store.budget()
    payer = person_for(context, context.actor.login)

    if body.to == payer:
        raise ApiError("self_settlement", "you cannot settle up with yourself")
    if not any(m.person == body.to for m in budget.members):
        raise not_found(f"person {body.to!r}")

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
