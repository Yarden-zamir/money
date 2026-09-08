# money

Budgeting and shared expenses for one person or a household. Envelope budgeting like YNAB,
shared-expense balances like Splitwise, from the same records.

The API is the product: the web app and the CLI are both generated clients of it, so anything
the interface can do is scriptable. Budget data lives in a private git repo, not a database —
readable, diffable, and yours even if this app disappears.

## The Idea

Every entry answers two independent questions:

- **Who paid?** — actual cash movement.
- **Who bears it, out of whose envelope?** — cost attribution.

A 50 shekel coffee that Yarden pays for, split with Dana, books 25 against each person's own
`fun-money` envelope and leaves Dana owing Yarden 25. The debt is never stored; it is the
difference between the two, folded from history on every read.

```yaml
# ledger/2026-07.yaml
- id: 01K9VYQ2N3X8R4T7B0M6D5C1FA
  kind: expense
  date: 2026-07-14
  payee: קפה גרג
  amount: -50.00
  currency: ILS
  paid_by:
    yarden: -50.00
  shares:
    - person: yarden
      amount: -25.00
      bucket: fun-money
    - person: dana
      amount: -25.00
      bucket: fun-money
```

The split comes from the bucket's default and is on the form for every entry, so the common
case is one line of input and the uncommon one — equally, by percent, by shares, exact,
"plus 60 for the wine", just me, or by receipt line — is a tap on the same panel. It applies at
creation time only: editing a bucket's default never rewrites what already happened.

An entry can carry a conversation (`comments/<id>.yaml`, shown as chat) and receipt photos
(`attachments/<id>/`), both committed to the same repo, so the question "what was this 284
shekel charge" has an answer six weeks later.

## Using It

```bash
money auth login                                  # GitHub device flow, like gh
money budget connect joint Yarden-zamir/budget-joint
money budget default joint

money entry add -- -50.00 "קפה גרג" -b fun-money      # an expense names its bucket
money month 2026-07
money balance
money settle dana --amount 25.00

money entry list --q "wine dana"                  # every word must match somewhere
money comment add 01K9VYQ2N3X8R4T7B0M6D5C1FA "did you keep the receipt?"

money api /budgets/joint/entries --query month=2026-07   # raw escape hatch
```

Every command exists because a route declared it. `--json` on any of them gives the raw
response.

## Running It Locally

```bash
uv sync --extra server
DEV_MODE=1 uv run uvicorn money.api.app:app --reload    # API on :8000

cd web && pnpm install && pnpm run dev                  # app on :5173, proxying /api
```

`DEV_MODE=1` skips GitHub auth with a stand-in user, and is rejected in any real deployment.

Regenerate the clients after changing a route:

```bash
uv run money generate-cli                               # Python CLI
uv run python -c "import json; from money.api.app import create_app; json.dump(create_app().openapi(), open('openapi.json','w'), indent=2)"
cd web && pnpm run generate:api                         # TypeScript
```

CI fails if either is stale.

## Hebrew

Hebrew is a first-class language, not a translation layered on an English layout. Logical CSS
properties throughout, `dir` driven by the active language, `Intl` for every number and date,
and amounts wrapped in bidi isolates so a minus sign cannot end up on the wrong side.

## Data And Access

One private GitHub repo per budget. Sharing a budget is adding a collaborator; revoking is
removing them. The app keeps no sharing model of its own — push access means write, pull
access means read, and a repo you cannot see returns 404 rather than confirming it exists.

Writes are pushed with the acting user's own GitHub token, so GitHub enforces permissions and
`git blame` attributes correctly.

## Deployment

[KitSHn](https://github.com/Yarden-zamir/kitshn) onto the VPS: `main` to
`money.yarden-zamir.com`, every pull request to `pr.<number>.money.yarden-zamir.com`. A
preview reads the real data repo on a branch named after its environment, created from `main`
on first use, so it never writes to production data.

## Specs

Behaviour contracts, kept true as the code changes:

[Data model](specs/data-model.md) ·
[API and auth](specs/api-and-auth.md) ·
[CLI](specs/cli.md) ·
[Web and RTL](specs/web-and-rtl.md) ·
[Deployment](specs/deployment.md) ·
[Currency](specs/currency.md)

## License

MIT
