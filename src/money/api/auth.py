"""Sessions, API keys, and token encryption."""

from __future__ import annotations

import base64
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, URLSafeTimedSerializer

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
