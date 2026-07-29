"""One error shape for the whole API, so clients parse errors once."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(message)


def not_found(what: str) -> ApiError:
    return ApiError("not_found", f"{what} not found", status=404)


def forbidden(message: str) -> ApiError:
    return ApiError("forbidden", message, status=403)


async def handle_api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


def _describe_location(location: tuple | list) -> str:
    """Turn pydantic's ("body", "shares", 0, "amount") into "shares.0.amount"."""
    parts = [str(part) for part in location if part not in ("body", "query", "path")]
    return ".".join(parts) or "request"


async def handle_request_validation_error(_: Request, exc: Exception) -> JSONResponse:
    """FastAPI rejects a malformed request body before any route runs.

    Its default response is `{"detail": [...]}`, which is not the envelope every other error
    uses — clients that parse `error.message` got an object and rendered "[object Object]".
    This maps it onto the same shape, naming the fields that failed.
    """
    raw = getattr(exc, "errors", lambda: [])()
    fields = {
        _describe_location(item.get("loc", ())): item.get("msg", "is invalid") for item in raw
    }
    summary = "; ".join(f"{name}: {message}" for name, message in fields.items())

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": summary or "the request body is not valid",
                "details": {"fields": fields},
            }
        },
    )


async def handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    """Pydantic errors from the domain reach here.

    A ledger file that does not balance raises during model validation on *read*, so this
    also covers hand-edited data that is internally inconsistent.
    """
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_data", "message": str(exc), "details": None}},
    )
