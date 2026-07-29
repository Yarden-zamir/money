"""GitHub as identity provider and as the authorization system.

The app keeps no sharing model of its own: whether someone may read or write a budget is
whether GitHub says they may read or write the repo behind it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

API = "https://api.github.com"
OAUTH = "https://github.com/login/oauth"
ACCEPT = "application/vnd.github+json"


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    name: str
    email: str
    avatar_url: str | None


@dataclass(frozen=True)
class RepoAccess:
    can_read: bool
    can_write: bool


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


def _client(token: str | None = None) -> httpx.Client:
    headers = {"Accept": ACCEPT, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(headers=headers, timeout=15.0)


def exchange_code(code: str, client_id: str, client_secret: str) -> str:
    with _client() as client:
        response = client.post(
            f"{OAUTH}/access_token",
            data={"client_id": client_id, "client_secret": client_secret, "code": code},
            headers={"Accept": "application/json"},
        )
    payload = response.json()
    if "access_token" not in payload:
        raise GitHubError(f"github rejected the code: {payload.get('error_description', payload)}")
    return payload["access_token"]


def start_device_flow(client_id: str, scope: str) -> DeviceCode:
    with _client() as client:
        response = client.post(
            f"{OAUTH}/device/code",
            data={"client_id": client_id, "scope": scope},
            headers={"Accept": "application/json"},
        )
    payload = response.json()
    if "device_code" not in payload:
        raise GitHubError(f"could not start device flow: {payload}")
    return DeviceCode(
        device_code=payload["device_code"],
        user_code=payload["user_code"],
        verification_uri=payload["verification_uri"],
        interval=int(payload.get("interval", 5)),
        expires_in=int(payload.get("expires_in", 900)),
    )


def poll_device_flow(device_code: str, client_id: str) -> str | None:
    """One poll. Returns the token, or None while the user has not approved yet.

    A hard failure (expired, denied) raises, so the caller can stop polling instead of
    looping until the code expires.
    """
    with _client() as client:
        response = client.post(
            f"{OAUTH}/access_token",
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
        )
    payload = response.json()
    if "access_token" in payload:
        return payload["access_token"]

    error = payload.get("error")
    if error in ("authorization_pending", "slow_down"):
        return None
    raise GitHubError(f"device flow failed: {payload.get('error_description', error)}")


def fetch_user(token: str) -> GitHubUser:
    with _client(token) as client:
        response = client.get(f"{API}/user")
        if response.status_code != 200:
            raise GitHubError(f"could not read the GitHub user: {response.text}")
        user = response.json()

        email = user.get("email")
        if not email:
            # A user with a private email has none on /user; the commit author still needs
            # one, and GitHub's noreply address is the correct thing to use.
            emails = client.get(f"{API}/user/emails")
            if emails.status_code == 200:
                primary = next((e for e in emails.json() if e.get("primary")), None)
                email = primary["email"] if primary else None
            email = email or f"{user['id']}+{user['login']}@users.noreply.github.com"

    return GitHubUser(
        id=user["id"],
        login=user["login"],
        name=user.get("name") or user["login"],
        email=email,
        avatar_url=user.get("avatar_url"),
    )


def repo_access(token: str, repo: str) -> RepoAccess:
    """What the token's owner may do with `owner/repo`.

    A repo they cannot see is indistinguishable from one that does not exist, which is what
    the API surface wants: no confirming the existence of a private repo to an outsider.
    """
    with _client(token) as client:
        response = client.get(f"{API}/repos/{repo}")
    if response.status_code == 404:
        return RepoAccess(can_read=False, can_write=False)
    if response.status_code != 200:
        raise GitHubError(f"could not read repo {repo}: {response.text}")

    permissions = response.json().get("permissions") or {}
    return RepoAccess(
        can_read=bool(permissions.get("pull")),
        can_write=bool(permissions.get("push") or permissions.get("admin")),
    )


@dataclass(frozen=True)
class RepoSummary:
    full_name: str
    private: bool
    can_write: bool
    description: str | None
    pushed_at: str | None


@dataclass(frozen=True)
class UserSummary:
    login: str
    name: str | None
    avatar_url: str | None


@dataclass(frozen=True)
class Collaborator:
    login: str
    name: str | None
    avatar_url: str | None
    permission: str
    invited: bool


def list_repos(token: str, limit: int = 100) -> list[RepoSummary]:
    """Repos the token's owner can see, most recently pushed first."""
    repos: list[RepoSummary] = []
    with _client(token) as client:
        for page in (1, 2):
            response = client.get(
                f"{API}/user/repos",
                params={
                    "per_page": 50,
                    "page": page,
                    "sort": "pushed",
                    "affiliation": "owner,collaborator,organization_member",
                },
            )
            if response.status_code != 200:
                raise GitHubError(f"could not list repos: {response.text}")
            batch = response.json()
            repos += [
                RepoSummary(
                    full_name=item["full_name"],
                    private=item["private"],
                    can_write=bool((item.get("permissions") or {}).get("push")),
                    description=item.get("description"),
                    pushed_at=item.get("pushed_at"),
                )
                for item in batch
            ]
            if len(batch) < 50:
                break
    return repos[:limit]


def has_file(token: str, repo: str, path: str) -> bool:
    """Whether a path exists in a repo's default branch."""
    with _client(token) as client:
        response = client.get(f"{API}/repos/{repo}/contents/{path}")
    return response.status_code == 200


def search_users(token: str, query: str, limit: int = 8) -> list[UserSummary]:
    """Search GitHub accounts by login or name.

    Used to autocomplete who to invite, so a typo in a username becomes a visible "no such
    user" instead of an invitation that silently goes nowhere.
    """
    if not query.strip():
        return []
    with _client(token) as client:
        response = client.get(
            f"{API}/search/users", params={"q": f"{query} type:user", "per_page": limit}
        )
        if response.status_code != 200:
            raise GitHubError(f"user search failed: {response.text}")
        found = response.json().get("items", [])

        # The search result carries no display name, so fill it in for the few shown.
        summaries: list[UserSummary] = []
        for item in found[:limit]:
            detail = client.get(f"{API}/users/{item['login']}")
            name = detail.json().get("name") if detail.status_code == 200 else None
            summaries.append(
                UserSummary(login=item["login"], name=name, avatar_url=item.get("avatar_url"))
            )
    return summaries


def list_collaborators(token: str, repo: str) -> list[Collaborator]:
    """Current collaborators plus anyone with an invitation still pending.

    Pending invitations matter: without them an invited person simply does not appear, and
    it looks like the invite failed.
    """
    people: list[Collaborator] = []
    with _client(token) as client:
        current = client.get(f"{API}/repos/{repo}/collaborators", params={"per_page": 100})
        if current.status_code != 200:
            raise GitHubError(f"could not list collaborators: {current.text}")
        for item in current.json():
            permissions = item.get("permissions") or {}
            people.append(
                Collaborator(
                    login=item["login"],
                    name=item.get("name"),
                    avatar_url=item.get("avatar_url"),
                    permission="admin"
                    if permissions.get("admin")
                    else "write"
                    if permissions.get("push")
                    else "read",
                    invited=False,
                )
            )

        pending = client.get(f"{API}/repos/{repo}/invitations", params={"per_page": 100})
        if pending.status_code == 200:
            for item in pending.json():
                invitee = item.get("invitee") or {}
                people.append(
                    Collaborator(
                        login=invitee.get("login", "?"),
                        name=invitee.get("name"),
                        avatar_url=invitee.get("avatar_url"),
                        permission=item.get("permissions", "write"),
                        invited=True,
                    )
                )
    return people


def invite_collaborator(token: str, repo: str, login: str, permission: str = "push") -> bool:
    """Invite someone to the data repo. True if a new invitation was created.

    GitHub answers 201 with an invitation for someone new and 204 when they already have
    access, so the caller can tell "invited" from "already a member".
    """
    with _client(token) as client:
        response = client.put(
            f"{API}/repos/{repo}/collaborators/{login}", json={"permission": permission}
        )
    if response.status_code == 201:
        return True
    if response.status_code == 204:
        return False
    if response.status_code == 404:
        raise GitHubError(f"no GitHub user named {login!r}, or you cannot administer {repo}")
    raise GitHubError(f"could not invite {login}: {response.text}")


def remove_collaborator(token: str, repo: str, login: str) -> None:
    with _client(token) as client:
        response = client.delete(f"{API}/repos/{repo}/collaborators/{login}")
    if response.status_code not in (204, 404):
        raise GitHubError(f"could not remove {login}: {response.text}")


class AccessCache:
    """Caches repo access briefly.

    This is a latency measure, not a security boundary: a revoked collaborator loses access
    within the TTL rather than instantly. Shorten it if that ever proves too slow.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl = ttl_seconds
        self._entries: dict[tuple[str, str], tuple[float, RepoAccess]] = {}

    def get(self, login: str, repo: str, token: str) -> RepoAccess:
        key = (login.casefold(), repo.casefold())
        cached = self._entries.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < self.ttl:
            return cached[1]

        access = repo_access(token, repo)
        self._entries[key] = (now, access)
        return access

    def invalidate(self, login: str, repo: str) -> None:
        self._entries.pop((login.casefold(), repo.casefold()), None)
