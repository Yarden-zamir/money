"""The signed-in user and their API keys."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from money.api import db
from money.api.deps import CurrentUser, current_user, get_session
from money.api.errors import ApiError, not_found
from money.api.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse, UserResponse

router = APIRouter(prefix="/me", tags=["me"])

VALID_SCOPES = {"read", "write", "admin"}


def _to_response(key: db.ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        scopes=key.scopes.split(","),
        created_at=key.created_at.isoformat(),
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
    )


@router.get(
    "",
    operation_id="getMe",
    response_model=UserResponse,
    summary="Who am I",
    openapi_extra={"x-cli": {"command": "auth whoami", "summary": "Show the signed-in user"}},
)
def get_me(caller: Annotated[CurrentUser, Depends(current_user)]) -> UserResponse:
    return UserResponse(
        login=caller.user.login,
        name=caller.user.name,
        email=caller.user.email,
        avatar_url=caller.user.avatar_url,
    )


@router.get(
    "/keys",
    operation_id="listApiKeys",
    response_model=list[ApiKeyResponse],
    summary="Your API keys",
    openapi_extra={"x-cli": {"command": "key list"}},
)
def list_keys(
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ApiKeyResponse]:
    keys = session.scalars(
        select(db.ApiKey).where(db.ApiKey.user_id == caller.user.id).order_by(db.ApiKey.id)
    )
    return [_to_response(key) for key in keys]


@router.post(
    "/keys",
    operation_id="createApiKey",
    response_model=ApiKeyCreated,
    status_code=201,
    summary="Create an API key",
    openapi_extra={"x-cli": {"command": "key create", "args": ["name"]}},
)
def create_key(
    body: ApiKeyCreate,
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> ApiKeyCreated:
    """The token is returned once here and never again; only its hash is stored."""
    unknown = set(body.scopes) - VALID_SCOPES
    if unknown:
        raise ApiError(
            "unknown_scope",
            f"unknown scopes: {', '.join(sorted(unknown))}",
            details={"valid": sorted(VALID_SCOPES)},
        )
    if "admin" not in caller.scopes and "admin" in body.scopes:
        # Otherwise a leaked read-only key could mint itself an admin one.
        raise ApiError("scope_escalation", "this credential cannot create an admin key", status=403)

    token, token_hash = db.mint_token()
    key = db.ApiKey(
        user_id=caller.user.id,
        name=body.name,
        token_hash=token_hash,
        scopes=",".join(body.scopes),
        expires_at=(
            db.utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
        ),
    )
    session.add(key)
    session.commit()

    return ApiKeyCreated(**_to_response(key).model_dump(), token=token)


@router.delete(
    "/keys/{key_id}",
    operation_id="deleteApiKey",
    status_code=204,
    summary="Revoke an API key",
    openapi_extra={"x-cli": {"command": "key delete", "args": ["key_id"]}},
)
def delete_key(
    key_id: int,
    caller: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    key = session.get(db.ApiKey, key_id)
    if key is None or key.user_id != caller.user.id:
        raise not_found(f"api key {key_id}")
    session.delete(key)
    session.commit()
