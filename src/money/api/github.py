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
