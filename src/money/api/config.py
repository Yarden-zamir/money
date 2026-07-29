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

    # KitSHn supplies these. Absent when running locally.
    kitshn_environment: str = "local"
    kitshn_data_dir: Path = Path("./var")
    kitshn_default_socket: str | None = None

    base_url: str = "http://localhost:8000"
    dev_mode: bool = Field(default=False, description="Bypass GitHub auth with a fake user")

    @property
    def data_branch(self) -> str:
        """Which branch of the data repo this deployment reads and writes.

        Production is `main`; every other environment uses its own name, so a KitSHn PR
        preview at `pr-42` works on branch `pr-42` and cannot corrupt production data.
        """
        return "main" if self.kitshn_environment in ("prod", "local") else self.kitshn_environment

    @property
    def db_path(self) -> Path:
        return self.kitshn_data_dir / "app.db"

    @property
    def repos_dir(self) -> Path:
        return self.kitshn_data_dir / "repos"

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
