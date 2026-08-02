"""FastAPI application.

One process serves the API and the built frontend from the same origin, which is what makes
the session cookie work without CORS configuration or a cookie-domain rule.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from money.api import db
from money.api.cache import Cache
from money.api.config import settings
from money.api.errors import (
    ApiError,
    handle_api_error,
    handle_request_validation_error,
    handle_validation_error,
)
from money.api.routes import (
    auth_routes,
    budgets,
    entries,
    github_routes,
    history,
    me,
    rules,
    scheduled,
    suggest_routes,
)
from money.store.store import DataError

API_PREFIX = "/api/v1"


def web_dist() -> Path:
    """Where the built frontend lives.

    In the image the package is installed non-editable, so this file sits in site-packages
    and nothing useful is relative to it — `WEB_DIST` is set explicitly there. The fallback
    is the repo layout, which is what a local checkout wants.

    Read straight from the environment rather than through `Settings`: the app is constructed
    at import time, and `Settings` validates that the deployment secrets are present. Routing
    a static path through it would make merely importing this module require them.
    """
    configured = os.environ.get("WEB_DIST")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = settings()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.sessionmaker = db.make_sessionmaker(config.db_path)
    app.state.cache = Cache(config.redis_url)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="money",
        version="0.1.0",
        description="Budgeting and shared-expense tracking, API first, git-backed.",
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )

    app.add_exception_handler(ApiError, handle_api_error)
    # Registered explicitly: FastAPI installs its own handler for this one, and its default
    # response shape is not the envelope the rest of the API uses.
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(ValidationError, handle_validation_error)
    app.add_exception_handler(DataError, _handle_data_error)

    for router in (
        auth_routes.router,
        budgets.router,
        entries.router,
        rules.router,
        me.router,
        github_routes.router,
        github_routes.collaborators,
        scheduled.router,
        history.router,
        suggest_routes.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    _add_health(app)
    _mount_web(app)
    return app


async def _handle_data_error(_, exc: Exception) -> JSONResponse:
    """A problem with the data repo itself: missing budget.yaml, a malformed ledger."""
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_data", "message": str(exc), "details": None}},
    )


def _add_health(app: FastAPI) -> None:
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Liveness only.

        Deliberately does not touch the data repo: a GitHub outage must not make Docker
        restart a container that is still serving cached reads.
        """
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, str]:
        config = settings()
        return {
            "status": "ok",
            "environment": config.kitshn_environment,
            "data_branch": config.data_branch,
        }


def _mount_web(app: FastAPI) -> None:
    """Serve the built SPA, falling back to index.html for client-side routes.

    Absent in development, where Vite serves the frontend and proxies the API.
    """
    dist = web_dist()
    if not dist.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
