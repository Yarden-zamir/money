"""The `money` CLI.

Hand-written commands cover auth, config, and the raw `api` escape hatch. Everything else is
generated from `x-cli` annotations on the routes — see specs/cli.md.
"""

from __future__ import annotations

import json
import time
import webbrowser
from pathlib import Path
from typing import Annotated, Any

import typer

from money_cli import config, generated
from money_cli.client import CliError, console, emit, err_console, request

app = typer.Typer(
    no_args_is_help=True,
    help="Budgeting and shared expenses, from the terminal.",
    add_completion=True,
)
generated.register(app)

# The generated `auth` group already exists (from `auth whoami`); extend it rather than
# adding a second group of the same name, which would shadow the generated commands.
auth_app = generated.auth_app
auth_app.info.help = "Authenticate with a money server"


@auth_app.command("login")
def auth_login(
    host: Annotated[str | None, typer.Option("--host", help="Server host")] = None,
    name: Annotated[str, typer.Option("--name", help="Label for the new API key")] = "cli",
) -> None:
    """Sign in through GitHub and store an API key.

    Uses GitHub's device flow, so no secret is ever pasted into the terminal.
    """
    target = host or config.DEFAULT_HOST
    start = request("POST", "/auth/device/start", host=target, require_auth=False)

    console.print(
        f"\n  Your one-time code: [bold cyan]{start['user_code']}[/bold cyan]\n"
        f"  Opening [link]{start['verification_uri']}[/link]\n"
    )
    webbrowser.open(start["verification_uri"])
    console.print("Waiting for approval… (Ctrl-C to cancel)")

    interval = max(int(start.get("interval", 5)), 1)
    deadline = time.monotonic() + 900

    while time.monotonic() < deadline:
        time.sleep(interval)
        result = request(
            "POST",
            "/auth/device/poll",
            body={"device_code": start["device_code"], "name": name},
            host=target,
            require_auth=False,
        )
        if result["status"] == "complete":
            config.save(config.HostConfig(host=target, token=result["token"], user=result["login"]))
            console.print(f"[green]✓[/green] Signed in to {target} as {result['login']}")
            console.print(f"  Token saved to {config.config_path()}")
            return

    raise CliError("the device code expired before it was approved")


@auth_app.command("status")
def auth_status(host: Annotated[str | None, typer.Option("--host")] = None) -> None:
    """Show who you are signed in as."""
    cfg = config.load(host)
    if not cfg.token:
        raise CliError(f"not signed in to {cfg.host}. Run: money auth login", 4)

    me = request("GET", "/me", host=host)
    console.print(f"[green]✓[/green] {cfg.host} — signed in as [bold]{me['login']}[/bold]")
    if cfg.default_budget:
        console.print(f"  default budget: {cfg.default_budget}")


@auth_app.command("logout")
def auth_logout(host: Annotated[str | None, typer.Option("--host")] = None) -> None:
    """Remove stored credentials for a host."""
    target = config.load(host).host
    if config.forget(target):
        console.print(f"[green]✓[/green] Removed credentials for {target}")
        return
    err_console.print(f"no stored credentials for {target}")


@app.command("api")
def api(
    path: Annotated[str, typer.Argument(help="API path, e.g. /budgets/joint/entries")],
    method: Annotated[str, typer.Option("--method", "-X", help="HTTP method")] = "GET",
    field: Annotated[
        list[str], typer.Option("--field", "-f", help="Body field as key=value, repeatable")
    ] = [],
    raw: Annotated[str | None, typer.Option("--raw", help="Raw JSON body")] = None,
    query: Annotated[
        list[str], typer.Option("--query", "-q", help="Query parameter as key=value")
    ] = [],
    host: Annotated[str | None, typer.Option("--host")] = None,
) -> None:
    """Call any endpoint directly, like `gh api`.

    This is the escape hatch: a new endpoint is usable the day it ships, without waiting for
    a CLI release.
    """
    body: dict[str, Any] | None = None
    if raw:
        body = json.loads(raw)
    if field:
        body = (body or {}) | dict(_split_pair(item) for item in field)

    result = request(
        method.upper(),
        path if path.startswith("/") else f"/{path}",
        query=dict(_split_pair(item) for item in query) or None,
        body=body,
        host=host,
    )
    emit(result, as_json=True)


@app.command("generate-cli")
def generate_cli(
    source: Annotated[str, typer.Argument(help="'app', a path to openapi.json, or a URL")] = "app",
    out: Annotated[Path, typer.Option("--out", help="Where to write the generated module")] = Path(
        __file__
    ).parent
    / "generated.py",
    check: Annotated[
        bool, typer.Option("--check", help="Fail if the file is out of date instead of writing")
    ] = False,
) -> None:
    """Regenerate CLI commands from the API schema.

    `--check` is what CI runs: a route whose annotation changed without regenerating fails
    the build rather than shipping a CLI that disagrees with the server.
    """
    from money_cli.generate import generate, load_spec

    rendered = generate(load_spec(source))
    if check:
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        if current != rendered:
            raise CliError(f"{out} is out of date. Run: money generate-cli")
        console.print(f"[green]✓[/green] {out} is up to date")
        return

    out.write_text(rendered, encoding="utf-8")
    console.print(f"[green]✓[/green] Wrote {out}")


@generated.budget_app.command("default")
def budget_default(
    slug: Annotated[str, typer.Argument(help="Budget slug to use when --budget is omitted")],
    host: Annotated[str | None, typer.Option("--host")] = None,
) -> None:
    """Set the budget used when a command gets no --budget.

    Registered onto the generated `budget` group rather than a second group of the same
    name, which would shadow the generated commands.
    """
    cfg = config.load(host)
    cfg.default_budget = slug
    config.save(cfg)
    console.print(f"[green]✓[/green] Default budget for {cfg.host} is now {slug}")


def _split_pair(item: str) -> tuple[str, str]:
    key, separator, value = item.partition("=")
    if not separator:
        raise CliError(f"expected key=value, got {item!r}", 2)
    return key, value


if __name__ == "__main__":
    app()
