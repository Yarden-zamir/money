"""HTTP plumbing and output rendering shared by every command."""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

from money_cli import config

API_PREFIX = "/api/v1"

# Exit codes, per specs/cli.md.
EXIT_API_ERROR = 1
EXIT_NOT_AUTHENTICATED = 4

console = Console()
err_console = Console(stderr=True)


class CliError(typer.Exit):
    def __init__(self, message: str, code: int = EXIT_API_ERROR) -> None:
        err_console.print(f"[red]error:[/red] {message}")
        super().__init__(code)


def request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    host: str | None = None,
    require_auth: bool = True,
) -> Any:
    cfg = config.load(host)
    if require_auth and not cfg.token:
        raise CliError(
            f"not signed in to {cfg.host}. Run: money auth login", EXIT_NOT_AUTHENTICATED
        )

    headers = {"Accept": "application/json"}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"

    url = f"{cfg.base_url}{API_PREFIX}{path}"
    try:
        response = httpx.request(
            method,
            url,
            params=_clean(query),
            json=_clean(body) if body is not None else None,
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )
    except httpx.RequestError as exc:
        raise CliError(f"could not reach {cfg.base_url}: {exc}") from exc

    if response.status_code == 204:
        return None
    if response.status_code >= 400:
        raise CliError(_describe_error(response))
    return response.json()


def _describe_error(response: httpx.Response) -> str:
    """Render the API's error envelope, falling back to raw text for anything else."""
    try:
        error = response.json()["error"]
    except json.JSONDecodeError, KeyError, TypeError:
        return f"HTTP {response.status_code}: {response.text[:400]}"

    message = f"{error['message']} ({error['code']})"
    details = error.get("details")
    return f"{message}\n{json.dumps(details, ensure_ascii=False)}" if details else message


def _clean(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop unset values so an omitted flag is absent rather than explicitly null."""
    if data is None:
        return None
    return {key: value for key, value in data.items() if value is not None and value != []}


def resolve_budget(budget: str | None, host: str | None = None) -> str:
    chosen = budget or config.load(host).default_budget
    if not chosen:
        raise CliError(
            "no budget given and no default set. Pass --budget, or run: money budget default <slug>"
        )
    return chosen


def emit(data: Any, *, as_json: bool, table: str | None = None) -> None:
    """Print a result: JSON when asked or when piped, a Rich table otherwise.

    Detecting a pipe matters because the table layout is not a contract; a script that
    forgot `--json` still gets machine-readable output instead of box drawing.
    """
    if as_json or not sys.stdout.isatty():
        console.print_json(json.dumps(data, ensure_ascii=False, default=str))
        return

    renderer = TABLES.get(table or "")
    if renderer is None or not data:
        console.print_json(json.dumps(data, ensure_ascii=False, default=str))
        return
    renderer(data)


def _amount(value: str) -> str:
    """Colour money by sign. Kept LTR so a minus sign never reorders next to Hebrew."""
    colour = "red" if str(value).startswith("-") else "green"
    return f"[{colour}]⁦{value}⁩[/{colour}]"


def render_entries(data: dict[str, Any]) -> None:
    table = Table(title=f"{data['total']} entries", box=None, pad_edge=False)
    for column in ("date", "payee", "amount", "buckets", "id"):
        table.add_column(column, justify="right" if column == "amount" else "left")

    for entry in data["entries"]:
        buckets = ", ".join(sorted({s["bucket"] for s in entry["shares"] if s["bucket"]}))
        table.add_row(
            entry["date"],
            entry["payee"],
            _amount(entry["amount"]),
            buckets or "—",
            entry["id"][-6:],
        )
    console.print(table)


def render_balances(data: dict[str, Any]) -> None:
    table = Table(title="balances", box=None, pad_edge=False)
    table.add_column("person")
    table.add_column("net", justify="right")
    for balance in data["balances"]:
        table.add_row(balance["person"], _amount(balance["net"]))
    console.print(table)

    if not data["settle_up"]:
        console.print("\n[green]all square[/green]")
        return
    console.print("\n[bold]to settle up:[/bold]")
    for payment in data["settle_up"]:
        console.print(
            f"  {payment['payer']} → {payment['payee']}  ⁦{payment['amount']} {data['currency']}⁩"
        )


def render_month(data: dict[str, Any]) -> None:
    console.print(
        f"[bold]{data['month']}[/bold] · {data['person']} · "
        f"ready to assign: {_amount(data['ready_to_assign'])} {data['currency']}"
    )
    table = Table(box=None, pad_edge=False)
    table.add_column("bucket")
    for column in ("assigned", "activity", "available"):
        table.add_column(column, justify="right")

    for bucket in data["buckets"]:
        table.add_row(
            bucket["name"],
            _amount(bucket["assigned"]),
            _amount(bucket["activity"]),
            _amount(bucket["available"]),
        )
    console.print(table)


def render_budgets(data: list[dict[str, Any]]) -> None:
    table = Table(box=None, pad_edge=False)
    for column in ("slug", "name", "repo", "you are", "access"):
        table.add_column(column)
    for budget in data:
        table.add_row(
            budget["slug"],
            budget["name"],
            budget["repo"],
            budget["me"] or "—",
            "write" if budget["can_write"] else "read",
        )
    console.print(table)


def render_keys(data: list[dict[str, Any]]) -> None:
    table = Table(box=None, pad_edge=False)
    for column in ("id", "name", "scopes", "created", "last used"):
        table.add_column(column)
    for key in data:
        table.add_row(
            str(key["id"]),
            key["name"],
            ",".join(key["scopes"]),
            key["created_at"][:10],
            (key["last_used_at"] or "never")[:10],
        )
    console.print(table)


TABLES = {
    "entries": render_entries,
    "balances": render_balances,
    "month": render_month,
    "budgets": render_budgets,
    "keys": render_keys,
}
