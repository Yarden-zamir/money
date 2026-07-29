"""CLI configuration, modelled on `gh`'s hosts.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_HOST = "money.yarden-zamir.com"


def config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(root) / "money" / "hosts.yaml"


@dataclass
class HostConfig:
    host: str
    token: str | None = None
    user: str | None = None
    default_budget: str | None = None

    @property
    def base_url(self) -> str:
        if self.host.startswith(("http://", "https://")):
            return self.host.rstrip("/")
        # Bare hostnames are https. Plain http must be spelled out, so a typo cannot
        # silently downgrade a request carrying a token.
        return f"https://{self.host}"


def load(host: str | None = None) -> HostConfig:
    """Resolve config. Environment wins over the file, so CI never needs to write one."""
    env_host = os.environ.get("MONEY_HOST")
    env_token = os.environ.get("MONEY_TOKEN")

    target = host or env_host or _default_host_from_file() or DEFAULT_HOST
    entries = _read_file()
    entry = entries.get(target, {})

    return HostConfig(
        host=target,
        token=env_token or entry.get("token"),
        user=entry.get("user"),
        default_budget=os.environ.get("MONEY_BUDGET") or entry.get("default_budget"),
    )


def save(config: HostConfig) -> None:
    entries = _read_file()
    entries[config.host] = {
        key: value
        for key, value in (
            ("token", config.token),
            ("user", config.user),
            ("default_budget", config.default_budget),
        )
        if value is not None
    }

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(entries, sort_keys=True), encoding="utf-8")
    # The file holds a credential, so it must not be world-readable.
    path.chmod(0o600)


def forget(host: str) -> bool:
    entries = _read_file()
    if host not in entries:
        return False
    del entries[host]
    config_path().write_text(yaml.safe_dump(entries, sort_keys=True), encoding="utf-8")
    return True


def _read_file() -> dict[str, dict[str, str]]:
    path = config_path()
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _default_host_from_file() -> str | None:
    entries = _read_file()
    return next(iter(entries), None)
