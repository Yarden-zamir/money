"""Runtime configuration.

Values arrive as plain environment variables. KitSHn strips the `KITSHN_` prefix from repo
secrets before they reach the container, so `KITSHN_SESSION_SECRET` on GitHub is
`SESSION_SECRET` here — see specs/deployment.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_client_id: str = ""
    github_client_secret: str = ""
    session_secret: str = ""
    token_encryption_key: str = ""

    default_data_repo: str | None = None

    # KitSHn supplies the environment name; the branch is derived from it below.
    kitshn_environment: str = "local"

    # Where this process writes its own state. This is a *container* path: compose mounts the
    # KitSHn host data directory onto it, so the two must not be conflated.
    data_dir: Path = Path("./var")

    base_url: str = "http://localhost:8000"

    # Optional. Absent means every read goes to git and GitHub, which is correct but slower.
    redis_url: str | None = None

    # Optional. Without it, a place has to be named by hand the first time.
    google_cloud_api_key: str = ""

    dev_mode: bool = Field(default=False, description="Bypass GitHub auth with a fake user")

    @property
    def is_production(self) -> bool:
        return self.kitshn_environment == "prod"

    @property
    def public_host(self) -> str:
        """Hostname of the production deployment, taken from BASE_URL.

        Previews are always `pr-<number>.<this host>`, which is what makes the sign-in
        handoff checkable rather than an open redirect.
        """
        return self.base_url.removeprefix("https://").removeprefix("http://").split("/")[0]

    @property
    def own_host(self) -> str:
        """This deployment's own hostname. Production and previews differ."""
        if self.is_production or self.kitshn_environment == "local":
            return self.public_host
        return f"{self.kitshn_environment}.{self.public_host}"

    def is_valid_preview_host(self, host: str) -> bool:
        """Is `host` a preview of *this* deployment?

        Deliberately strict, and built from parts rather than a pattern match: this value
        decides where a sign-in ticket gets sent, so anything but an exact
        `pr-<digits>.<public host>` must be refused.
        """
        label, dot, rest = host.partition(".")
        number = label.removeprefix("pr-")
        if not dot or not label.startswith("pr-") or not (number.isascii() and number.isdigit()):
            return False
        return rest == self.public_host

    @property
    def data_branch(self) -> str:
        """Which branch of the data repo this deployment reads and writes.

        Production is `main`; every other environment uses its own name, so a KitSHn PR
        preview at `pr-42` works on branch `pr-42` and cannot corrupt production data.
        """
        return "main" if self.kitshn_environment in ("prod", "local") else self.kitshn_environment

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @model_validator(mode="after")
    def _require_secrets_outside_dev(self) -> Self:
        """Fail at startup rather than at first login.

        A missing secret must crash the process, not silently produce a deployment where
        sessions cannot be verified or tokens cannot be decrypted.
        """
        if self.dev_mode:
            return self
        missing = [
            name
            for name in (
                "github_client_id",
                "github_client_secret",
                "session_secret",
                "token_encryption_key",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                f"missing required settings: {', '.join(missing)}. "
                "Set them as KITSHN_<NAME> repo secrets, or set DEV_MODE=1 for local work."
            )
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
