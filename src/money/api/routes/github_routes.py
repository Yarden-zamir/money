"""GitHub-backed discovery: which repos could be a budget, and who to invite.

These proxy GitHub with the caller's own token, so they can only ever see what that person
can already see. Nothing here uses a shared credential.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from money.api import db, github
from money.api.config import Settings
from money.api.deps import (
    BudgetContext,
    CurrentUser,
    budget_context,
    current_user,
    get_session,
    get_settings,
    github_token,
    writable,
)
from money.api.errors import ApiError
from money.api.schemas import (
    CollaboratorResponse,
    InviteRequest,
    InviteResponse,
    RepoOption,
    UserOption,
)
from money.domain.models import Budget, Member

router = APIRouter(prefix="/github", tags=["github"])

# How many of the caller's repos to probe for a budget.yaml. Each probe is one API call, so
# this is a latency budget, not a limit on what can be connected — the form still accepts any
# owner/repo typed by hand.
PROBE_LIMIT = 40


@router.get(
    "/repos",
    operation_id="listGithubRepos",
    response_model=list[RepoOption],
    summary="Repos you could connect as a budget",
)
def list_repos(
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> list[RepoOption]:
    """Lists the caller's repos, flagging which already look like a budget.

    "Looks like a budget" means it has a `budget.yaml`. That is checked for the most recently
    pushed repos only — one API call each — and everything else is still listed, just without
    the flag. Guessing wrong is cheap: connecting a repo without one fails with a clear error.
    """
    token = github_token(caller.user, config)
    repos = github.list_repos(token)

    connected = {link.repo.casefold() for link in session.scalars(select(db.BudgetLink))}

    writable_repos = [repo for repo in repos if repo.can_write]
    probes = writable_repos[:PROBE_LIMIT]

    # Probed concurrently: forty sequential round trips to GitHub would make this screen feel
    # broken. The pool is small so a slow GitHub does not tie up the whole worker.
    with ThreadPoolExecutor(max_workers=8) as pool:
        looks_like_budget = dict(
            zip(
                (repo.full_name for repo in probes),
                pool.map(
                    lambda repo: github.has_file(token, repo.full_name, "budget.yaml"), probes
                ),
                strict=True,
            )
        )

    options = [
        RepoOption(
            full_name=repo.full_name,
            private=repo.private,
            description=repo.description,
            is_budget=looks_like_budget.get(repo.full_name, False),
            connected=repo.full_name.casefold() in connected,
        )
        for repo in writable_repos
    ]
    # Budget-looking repos first, then already-connected ones last: the useful choices rise.
    options.sort(key=lambda option: (option.connected, not option.is_budget))
    return options


@router.get(
    "/users",
    operation_id="searchGithubUsers",
    response_model=list[UserOption],
    summary="Find a GitHub user to invite",
)
def search_users(
    caller: Annotated[CurrentUser, Depends(current_user)],
    config: Annotated[Settings, Depends(get_settings)],
    q: Annotated[str, Query(min_length=1, max_length=64)],
) -> list[UserOption]:
    found = github.search_users(github_token(caller.user, config), q)
    return [
        UserOption(login=user.login, name=user.name, avatar_url=user.avatar_url) for user in found
    ]


collaborators = APIRouter(prefix="/budgets/{budget}", tags=["github"])


@collaborators.get(
    "/collaborators",
    operation_id="listCollaborators",
    response_model=list[CollaboratorResponse],
    summary="Who has access to the data repo",
)
def list_collaborators(
    context: Annotated[BudgetContext, Depends(budget_context)],
) -> list[CollaboratorResponse]:
    """Repo access is the real permission model, so this shows it directly.

    Pending invitations are included: without them someone just invited does not appear at
    all, and it looks as though the invitation failed.
    """
    people = github.list_collaborators(context.actor.token, context.repo)
    members = {
        member.github.casefold() for member in context.store.budget().members if member.github
    }

    return [
        CollaboratorResponse(
            login=person.login,
            name=person.name,
            avatar_url=person.avatar_url,
            permission=person.permission,
            invited=person.invited,
            is_member=person.login.casefold() in members,
        )
        for person in people
    ]


@collaborators.post(
    "/invite",
    operation_id="inviteCollaborator",
    response_model=InviteResponse,
    summary="Invite someone to the budget's data repo",
    openapi_extra={"x-cli": {"command": "member invite", "args": ["login"]}},
)
def invite(
    body: InviteRequest,
    context: Annotated[BudgetContext, Depends(writable)],
) -> InviteResponse:
    """Sends a real GitHub invitation, and adds them to the budget's member list.

    Both halves are needed and they are not the same thing: the invitation is what lets them
    sign in at all, and membership is what lets them hold a share of an entry. Doing only the
    first was the old behaviour, and it left people able to log in to a budget that could not
    reference them.
    """
    budget = context.store.budget()
    login = body.login.strip()

    try:
        newly_invited = github.invite_collaborator(context.actor.token, context.repo, login)
    except github.GitHubError as exc:
        raise ApiError("invite_failed", str(exc), status=400) from exc

    already = budget.person_for_github(login)
    if already is not None:
        return InviteResponse(login=login, invited=newly_invited, person=already)

    person = body.person or _person_id_from(login, {member.person for member in budget.members})

    # Built as a Member, not a dict: model_copy does not validate, so a raw dict would sit in
    # a typed list and only fail later, when the YAML is written.
    member = Member(person=person, name=body.name or login, github=login)
    updated = Budget.model_validate(
        budget.model_dump(mode="python") | {"members": [*budget.members, member]}
    )
    context.store.put_members(updated, context.actor)

    return InviteResponse(login=login, invited=newly_invited, person=person)


def _person_id_from(login: str, taken: set[str]) -> str:
    """Derive a person id from a GitHub login, keeping it unique within the budget."""
    base = "".join(character if character.isalnum() else "-" for character in login.lower())
    base = base.strip("-")[:39] or "person"

    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:36]}-{suffix}"
        if candidate not in taken:
            return candidate
    raise ApiError("person_id_taken", f"could not derive a free person id from {login!r}")
