"""Sessions, API keys, and token encryption."""

from __future__ import annotations

import base64
import secrets
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE = "money_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# The OAuth scopes the app needs: read the user's identity, and read/write the private repos
# that hold budget data.
OAUTH_SCOPES = "read:user user:email repo"


def fernet_for(secret: str) -> Fernet:
    """Accept any string as the encryption key.

    Fernet needs 32 url-safe base64 bytes; hashing whatever the operator supplied gets there
    without making them generate a key in a specific format.
    """
    return Fernet(base64.urlsafe_b64encode(sha256(secret.encode()).digest()))


def encrypt_token(token: str, secret: str) -> str:
    return fernet_for(secret).encrypt(token.encode()).decode()


def decrypt_token(encrypted: str, secret: str) -> str:
    try:
        return fernet_for(secret).decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        # Almost always means TOKEN_ENCRYPTION_KEY was rotated. Surfacing it clearly beats a
        # confusing 500 on the next data-repo write.
        raise ValueError(
            "stored GitHub token could not be decrypted; TOKEN_ENCRYPTION_KEY may have changed. "
            "Affected users must sign in again."
        ) from exc


def session_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="money-session")


def issue_session(user_id: int, secret: str) -> str:
    return session_serializer(secret).dumps({"uid": user_id})


def read_session(cookie: str, secret: str) -> int | None:
    try:
        payload = session_serializer(secret).loads(cookie, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    uid = payload.get("uid")
    return uid if isinstance(uid, int) else None


# ---- Preview sign-in handoff -------------------------------------------------------------
#
# A GitHub OAuth app has exactly one callback URL, so a PR preview cannot run its own OAuth
# flow. Production completes the flow and hands the result to the preview as a ticket.
#
# The ticket carries the user's GitHub token, so it is deliberately hostile to reuse:
#   * 60 second lifetime,
#   * pinned to one preview host, which the preview re-checks against its own hostname,
#   * single-use, enforced by the preview through the `jti` nonce,
#   * signed with SESSION_SECRET, which both deployments share and no client has.
# It still travels in a URL and therefore reaches browser history, which is why the window
# is this short. Widen it and that trade stops holding.

HANDOFF_MAX_AGE = 60


def handoff_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="money-preview-handoff")


def issue_handoff(*, github_token: str, host: str, secret: str, encryption_key: str) -> str:
    return handoff_serializer(secret).dumps(
        {
            "jti": secrets.token_urlsafe(16),
            "host": host,
            # Encrypted, not raw: the signature proves the ticket is ours, and this keeps the
            # token unreadable to anything that merely observes the URL.
            "token": encrypt_token(github_token, encryption_key),
        }
    )


class HandoffError(ValueError):
    """A preview sign-in ticket was invalid, expired, replayed, or meant for another host."""


# Consumed nonces, kept in process. A restart forgets them, which is safe: the ticket's own
# 60 second expiry has almost certainly passed, and a replay still has to beat that window.
_consumed: set[str] = set()


def read_handoff(ticket: str, *, expected_host: str, secret: str, encryption_key: str) -> str:
    """Validate a ticket and return the GitHub token it carries."""
    try:
        payload = handoff_serializer(secret).loads(ticket, max_age=HANDOFF_MAX_AGE)
    except SignatureExpired as exc:
        raise HandoffError("this sign-in link has expired; start again") from exc
    except BadSignature as exc:
        raise HandoffError("this sign-in link is not valid") from exc

    if payload.get("host") != expected_host:
        raise HandoffError("this sign-in link was issued for a different host")

    jti = payload.get("jti")
    if not isinstance(jti, str) or jti in _consumed:
        raise HandoffError("this sign-in link has already been used")
    _consumed.add(jti)

    return decrypt_token(payload["token"], encryption_key)
