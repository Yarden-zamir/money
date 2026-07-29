"""Sign-in flows: the browser's OAuth redirect and the CLI's device flow."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from money.api import auth, db, github
from money.api.config import Settings
from money.api.deps import get_session, get_settings
from money.api.errors import ApiError

router = APIRouter(prefix="/auth", tags=["auth"])

# Short-lived CSRF state for the browser flow, mapped to (started_at, return_host). In-process
# is fine: a restart only costs an in-flight sign-in, and there is one process per deployment.
_pending_states: dict[str, tuple[float, str | None]] = {}


class AuthConfig(BaseModel):
    login_url: str


class DeviceStart(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    interval: int


class DevicePoll(BaseModel):
    device_code: str
    name: str = "cli"


class DeviceResult(BaseModel):
    status: str  # "pending" or "complete"
    token: str | None = None
    login: str | None = None


def _upsert_user(
    session: Session, profile: github.GitHubUser, token: str, config: Settings
) -> db.User:
    """Create or refresh the user, always re-encrypting the freshest GitHub token.

    The stored token is what later pushes to the data repo, so a stale one would mean writes
    failing long after a successful sign-in.
    """
    user = session.scalar(select(db.User).where(db.User.github_id == profile.id))
    encrypted = auth.encrypt_token(token, config.token_encryption_key)

    if user is None:
        user = db.User(
            github_id=profile.id,
            login=profile.login,
            name=profile.name,
            email=profile.email,
            avatar_url=profile.avatar_url,
            encrypted_token=encrypted,
        )
        session.add(user)
    else:
        user.login = profile.login
        user.name = profile.name
        user.email = profile.email
        user.avatar_url = profile.avatar_url
        user.encrypted_token = encrypted

    session.commit()
    return user


@router.get("/config", operation_id="getAuthConfig", response_model=AuthConfig)
def get_auth_config(config: Annotated[Settings, Depends(get_settings)]) -> AuthConfig:
    """Where this deployment's sign-in starts.

    Computed server-side because only the server knows whether it is production or a preview;
    the browser guessing its own prod origin from the hostname would be one more thing to
    keep correct.
    """
    if config.is_production or config.kitshn_environment == "local":
        return AuthConfig(login_url=f"{config.base_url}/api/v1/auth/github/start")

    # A preview sends the user to production, which owns the single OAuth callback, and asks
    # for the finished session to be handed back here.
    return AuthConfig(
        login_url=(f"{config.base_url}/api/v1/auth/github/start?return_host={config.own_host}")
    )


@router.get("/github/start", operation_id="startGithubLogin", summary="Begin browser sign-in")
def start_github_login(
    config: Annotated[Settings, Depends(get_settings)],
    return_host: str | None = None,
) -> RedirectResponse:
    import time

    if return_host is not None and not config.is_valid_preview_host(return_host):
        # This value decides where a sign-in ticket is sent. Anything unrecognised is an
        # attempt to turn sign-in into an open redirect, so it is refused outright.
        raise ApiError("bad_return_host", f"{return_host!r} is not a preview of this app")

    state = secrets.token_urlsafe(24)
    _pending_states[state] = (time.monotonic(), return_host)

    query = {
        "client_id": config.github_client_id,
        "redirect_uri": f"{config.base_url}/api/v1/auth/github/callback",
        "scope": auth.OAUTH_SCOPES,
        "state": state,
    }
    encoded = "&".join(f"{key}={value}" for key, value in query.items())
    return RedirectResponse(f"{github.OAUTH}/authorize?{encoded}")


@router.get("/github/callback", operation_id="finishGithubLogin", summary="OAuth callback")
def finish_github_login(
    code: str,
    state: str,
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    import time

    pending = _pending_states.pop(state, None)
    if pending is None or time.monotonic() - pending[0] > 600:
        raise ApiError("bad_oauth_state", "sign-in expired or was tampered with", status=400)
    return_host = pending[1]

    token = github.exchange_code(code, config.github_client_id, config.github_client_secret)

    if return_host:
        # The session belongs on the preview host, not here. Hand the token over as a
        # short-lived single-use ticket and let the preview mint its own session.
        ticket = auth.issue_handoff(
            github_token=token,
            host=return_host,
            secret=config.session_secret,
            encryption_key=config.token_encryption_key,
        )
        return RedirectResponse(f"https://{return_host}/api/v1/auth/handoff?ticket={ticket}")

    user = _upsert_user(session, github.fetch_user(token), token, config)
    return _redirect_with_session(user, config)


@router.get("/handoff", operation_id="acceptHandoff", summary="Accept a preview sign-in ticket")
def accept_handoff(
    ticket: str,
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Complete a sign-in that production started on this preview's behalf.

    The ticket is checked against *this* deployment's own hostname, so a ticket minted for
    `pr-42` is useless at `pr-43` even though both trust the same signing key.
    """
    if config.is_production:
        raise ApiError("not_a_preview", "production completes its own sign-in", status=400)

    try:
        github_token = auth.read_handoff(
            ticket,
            expected_host=config.own_host,
            secret=config.session_secret,
            encryption_key=config.token_encryption_key,
        )
    except auth.HandoffError as exc:
        raise ApiError("bad_handoff", str(exc), status=400) from exc

    # The preview has its own database, so the user is created here from GitHub rather than
    # copied across. That also proves the token still works before a session is issued.
    user = _upsert_user(session, github.fetch_user(github_token), github_token, config)
    return _redirect_with_session(user, config)


def _redirect_with_session(user: db.User, config: Settings) -> RedirectResponse:
    redirect = RedirectResponse(url="/")
    redirect.set_cookie(
        auth.SESSION_COOKIE,
        auth.issue_session(user.id, config.session_secret),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,  # the SPA never reads this, so XSS cannot exfiltrate it
        secure=config.base_url.startswith("https"),
        samesite="lax",
        path="/",
    )
    return redirect


@router.post("/logout", operation_id="logout", status_code=204, summary="Sign out")
def logout(response: Response) -> None:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")


@router.post(
    "/device/start",
    operation_id="startDeviceLogin",
    response_model=DeviceStart,
    summary="Begin CLI sign-in",
)
def start_device_login(config: Annotated[Settings, Depends(get_settings)]) -> DeviceStart:
    code = github.start_device_flow(config.github_client_id, auth.OAUTH_SCOPES)
    return DeviceStart(
        device_code=code.device_code,
        user_code=code.user_code,
        verification_uri=code.verification_uri,
        interval=code.interval,
    )


@router.post(
    "/device/poll",
    operation_id="pollDeviceLogin",
    response_model=DeviceResult,
    summary="Exchange an approved device code for an API key",
)
def poll_device_login(
    body: DevicePoll,
    session: Annotated[Session, Depends(get_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> DeviceResult:
    """Returns `pending` until the user approves in their browser.

    On approval this mints a *money* API key rather than handing the CLI the GitHub token,
    so revoking CLI access never means revoking GitHub access.
    """
    github_token = github.poll_device_flow(body.device_code, config.github_client_id)
    if github_token is None:
        return DeviceResult(status="pending")

    user = _upsert_user(session, github.fetch_user(github_token), github_token, config)

    token, token_hash = db.mint_token()
    session.add(
        db.ApiKey(user_id=user.id, name=body.name, token_hash=token_hash, scopes="read,write")
    )
    session.commit()

    return DeviceResult(status="complete", token=token, login=user.login)


@router.get("/health", operation_id="authHealth", include_in_schema=False)
def auth_health(config: Annotated[Settings, Depends(get_settings)]) -> dict[str, bool]:
    return {"github_configured": bool(config.github_client_id)}
