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
from money.store.gitrepo import GitRepo
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


def budget_context(
    budget: str,
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[AccessCache, Depends(access_cache)],
    shared: Annotated[Cache, Depends(get_cache)],
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
    repo.ensure_clone(token)

    return BudgetContext(
        slug=link.slug,
        repo=link.repo,
        store=BudgetStore(repo, cache=shared),
        actor=Actor(
            login=caller.user.login,
            name=caller.user.name,
            email=caller.user.email,
            token=token,
        ),
        can_write=access.can_write and "write" in caller.scopes,
    )


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
    person = context.store.budget().person_for_github(login)
    if person is None:
        raise forbidden(
            f"{login} is not a member of budget {context.slug!r}; "
            "add them to members in budget.yaml"
        )
    return person
