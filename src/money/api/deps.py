"""Request dependencies: who is calling, and which budget they may touch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from money.api import auth, db
from money.api.cache import Cache
from money.api.config import Settings, settings
from money.api.errors import ApiError, forbidden, not_found
from money.api.github import AccessCache
from money.store.gitrepo import READ_MAX_AGE, GitRepo
from money.store.store import Actor, BudgetStore

# Process-wide, because the cache and clone locks must be shared across requests.
_access_cache = AccessCache()

# Repo access is a security-relevant value with no sha to key it against, so its staleness is
# bounded by time. Revoking someone takes effect within this window.
ACCESS_TTL_SECONDS = 300


def get_settings() -> Settings:
    return settings()


def get_session(request: Request) -> Session:
    factory = request.app.state.sessionmaker
    with factory() as session:
        yield session


def access_cache() -> AccessCache:
    return _access_cache


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


@dataclass(frozen=True)
class CurrentUser:
    user: db.User
    scopes: set[str]


def current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
    money_session: Annotated[str | None, Cookie(alias=auth.SESSION_COOKIE)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Resolve the caller from either a bearer API key or a session cookie.

    A bearer token wins when both are present, so a scripted call is never silently made with
    the browser's ambient session.
    """
    if authorization and authorization.lower().startswith("bearer "):
        return _user_from_api_key(authorization.split(" ", 1)[1].strip(), session)

    if money_session:
        uid = auth.read_session(money_session, config.session_secret)
        if uid is not None:
            user = session.get(db.User, uid)
            if user:
                # A browser session carries full rights; scopes exist to narrow API keys.
                return CurrentUser(user=user, scopes={"read", "write", "admin"})

    if config.dev_mode:
        return CurrentUser(user=_dev_user(session), scopes={"read", "write", "admin"})

    raise ApiError("unauthenticated", "sign in or supply an API key", status=401)


def _user_from_api_key(token: str, session: Session) -> CurrentUser:
    key = session.scalar(select(db.ApiKey).where(db.ApiKey.token_hash == db.hash_token(token)))
    if key is None or not key.is_valid():
        raise ApiError("invalid_api_key", "that API key is not valid", status=401)

    key.last_used_at = db.utcnow()
    session.commit()

    user = session.get(db.User, key.user_id)
    if user is None:
        raise ApiError("invalid_api_key", "that API key is not valid", status=401)
    return CurrentUser(user=user, scopes=set(key.scopes.split(",")))


def _dev_user(session: Session) -> db.User:
    """A stand-in identity so the API is usable locally without a GitHub OAuth app.

    Only reachable when DEV_MODE is set, which config rejects in any real deployment.
    """
    user = session.scalar(select(db.User).where(db.User.github_id == 0))
    if user is None:
        user = db.User(
            github_id=0,
            login="dev",
            name="Dev User",
            email="dev@localhost",
            encrypted_token="",
        )
        session.add(user)
        session.commit()
    return user


def require_write(caller: CurrentUser) -> None:
    if "write" not in caller.scopes:
        raise forbidden("this API key is read-only")


@dataclass
class BudgetContext:
    slug: str
    repo: str
    store: BudgetStore
    actor: Actor
    can_write: bool
    acting_as: str | None = None
    """Which member this request speaks for, when it is not the signed-in account.

    Only ever set for a placeholder member — one with no GitHub login. The commit author
    stays the real person, so `git log` still records who actually did it.
    """


def budget_context(
    budget: str,
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[AccessCache, Depends(access_cache)],
    shared: Annotated[Cache, Depends(get_cache)],
    act_as: Annotated[str | None, Header(alias="X-Act-As")] = None,
) -> BudgetContext:
    """Resolve a budget slug to a store, after checking GitHub says the caller may see it."""
    link = session.scalar(select(db.BudgetLink).where(db.BudgetLink.slug == budget))
    if link is None:
        raise not_found(f"budget {budget!r}")

    token = github_token(caller.user, config)
    access = _repo_access(caller.user.login, link.repo, token, shared, cache)
    if not access.can_read:
        # 404, not 403: do not confirm the repo exists to someone who cannot see it.
        raise not_found(f"budget {budget!r}")

    repo = GitRepo(
        path=repo_path(config.repos_dir, link.repo),
        remote=f"https://github.com/{link.repo}.git",
        branch=config.data_branch,
    )
    # A read, so it may use a clone fetched moments ago rather than pay for another
    # round trip to GitHub. Writes go through the store, which always fetches.
    repo.ensure_clone(token, max_age=READ_MAX_AGE)

    store = BudgetStore(repo, cache=shared)
    return BudgetContext(
        slug=link.slug,
        repo=link.repo,
        store=store,
        actor=Actor(
            login=caller.user.login,
            name=caller.user.name,
            email=caller.user.email,
            token=token,
        ),
        can_write=access.can_write and "write" in caller.scopes,
        acting_as=_acting_as(store, act_as),
    )


def _acting_as(store: BudgetStore, requested: str | None) -> str | None:
    """Resolve an `X-Act-As` header, or refuse it.

    Only a member with **no GitHub login** can be acted as. That single rule is what makes
    this safe rather than an impersonation hole: a person without a login is a placeholder
    nobody can sign in as, so acting as them speaks for a stand-in rather than for somebody
    real. A member with a login always speaks for themselves, and no header changes that.

    Without it this would let anyone with repo access attribute their spending to their
    partner, which is precisely the thing the ledger exists to record honestly.
    """
    if not requested:
        return None

    member = next((m for m in store.budget().members if m.person == requested), None)
    if member is None:
        raise not_found(f"member {requested!r}")
    if member.github:
        raise forbidden(
            f"{requested} is a real account and cannot be acted as; "
            "only placeholder members with no GitHub login can"
        )
    return member.person


def _repo_access(login: str, repo: str, token: str, shared: Cache, fallback: AccessCache):
    """Whether this person may read or write the repo, cached briefly.

    Not keyed by a commit sha, because it changes on GitHub with no commit here — so unlike
    every other cached value this one carries a real TTL, and a revocation takes effect
    within it. Falls back to the in-process cache when Redis is absent.
    """
    from money.api.cache import access_key
    from money.api.github import RepoAccess, repo_access

    if not shared.enabled:
        return fallback.get(login, repo, token)

    raw = shared.get_or_set(
        access_key(login, repo),
        lambda: repo_access(token, repo).__dict__,
        ttl=ACCESS_TTL_SECONDS,
    )
    return RepoAccess(**raw)


def writable(context: Annotated[BudgetContext, Depends(budget_context)]) -> BudgetContext:
    if not context.can_write:
        raise forbidden(f"you have read-only access to {context.repo}")
    return context


def repo_path(root: Path, repo: str) -> Path:
    owner, _, name = repo.partition("/")
    return root / owner / name


def github_token(user: db.User, config: Settings) -> str:
    if config.dev_mode and not user.encrypted_token:
        return ""
    return auth.decrypt_token(user.encrypted_token, config.token_encryption_key)


def person_for(context: BudgetContext, login: str) -> str:
    """Which member is acting.

    Normally the signed-in GitHub account. `context.acting_as` overrides it, but only for a
    member with **no GitHub login** — see `acting_as` for why that constraint is the whole
    security model here.
    """
    if context.acting_as is not None:
        return context.acting_as

    person = context.store.budget().person_for_github(login)
    if person is None:
        raise forbidden(
            f"{login} is not a member of budget {context.slug!r}; "
            "add them to members in budget.yaml"
        )
    return person
