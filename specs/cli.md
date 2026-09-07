# CLI

`money` is modelled on `gh`: a small set of hand-written commands for auth and config, a
generated command for every API operation, and a raw escape hatch so a new endpoint is usable
the day it ships without waiting for a CLI release.

```bash
money auth login                 # GitHub device flow, stores an API key
money auth status
money api /budgets/joint/entries --method POST --field amount=-50.00

money entry add -- -50.00 "קפה גרג" --bucket fun-money --split yarden=0.5,dana=0.5
money entry list --month 2026-07 --person yarden
money balance
money settle dana --amount 25.00
money month 2026-07
```

## First-Class Commands Come From Annotations

A route declares its CLI surface next to itself. Nothing about the CLI lives in a separate
mapping file that can drift from the routes.

```python
@router.post(
    "/budgets/{budget}/entries",
    operation_id="createEntry",
    openapi_extra={
        "x-cli": {
            "command": "entry add",
            "summary": "Record an entry",
            "args": ["amount", "payee"],          # positional, in this order
            "aliases": {"bucket": "-b", "month": "-m"},
        }
    },
)
```

`x-cli` rides along in the OpenAPI schema, so the generator needs no access to Python source
and the annotation is visible to any other client that wants it. A route with no `x-cli` is
still reachable through `money api`; it just gets no dedicated command.

The generator only understands JSON bodies. The attachment upload takes the file as a raw
body, so it has no command and `money api` cannot call it either — `curl --data-binary` with
a bearer token is the CLI path for a receipt photo until the generator grows a file option.

`money generate-cli` writes `src/money_cli/generated.py` from the schema. It is checked in and
regenerated in CI, which fails on a diff — the same rule the TypeScript client follows. Import
time stays free of network calls and schema parsing, so the CLI starts fast.

Typer builds the command tree from the generated module. Nested commands come from splitting
`command` on whitespace, so `"entry add"` produces `money entry add`.

## Output

Human output is Rich tables, right-aligned on money and correct for Hebrew payee names.
`--json` on any command emits the raw API response for piping into `jq`. Scripts should pass
`--json`; the table layout is not a contract and may change.

Exit codes: `0` success, `1` API error, `2` usage error, `4` not authenticated.

## Configuration

`~/.config/money/hosts.yaml`, same idea as `gh`:

```yaml
money.yarden-zamir.com:
  token: money_pat_…
  user: Yarden-zamir
  default_budget: joint
```

`MONEY_HOST` and `MONEY_TOKEN` override the file, which is what CI should use. A token in the
environment never gets written to disk.

## Distribution

`uvx --from git+https://github.com/Yarden-zamir/money.git money …` needs no install, and a
Homebrew tap formula mirrors how KitSHn ships. The CLI depends only on `httpx`, `typer`,
`rich`, and `pyyaml`; it does not import the server package, so installing it pulls in neither
FastAPI nor SQLAlchemy.
