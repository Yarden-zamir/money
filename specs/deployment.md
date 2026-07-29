# Deployment

Deployed with [KitSHn](https://github.com/Yarden-zamir/kitshn) onto the VPS. `main` goes to
`prod` at `money.yarden-zamir.com`; every pull request gets a preview at
`pr.<number>.money.yarden-zamir.com`.

```yaml
# .kitshn.yaml
deploy:
  - on: push
    branch: main
    name: prod

  - on: pull_request
    name: pr-{pr}
    ephemeral: true
```

## Ingress

Caddy on the host cannot resolve Compose service names, so the app is reached over a Unix
socket. Uvicorn binds `${KITSHN_DEFAULT_SOCKET}` directly — the app speaks the socket itself,
so there is no `socat` sidecar to keep alive.

The frontend is built at image build time and served by the same FastAPI process as static
files, with unknown paths falling back to `index.html` for client-side routing. One container,
one origin, no CORS configuration and no cookie-domain problems.

## Preview Deploys Use Real Data On Their Own Branch

A preview points at the **same** private data repo as production, on a branch named after its
environment. `MONEY_DATA_BRANCH` is derived from `KITSHN_ENVIRONMENT`: `prod` maps to `main`,
and anything else is used verbatim. `pr-42` therefore reads and writes `pr-42`.

The branch is created from `main` on first use if it does not exist. A preview sees production
data shapes and history, and its writes land somewhere deletable. Deleting the branch discards
everything the preview did.

🔴 A preview can still write to the real repo, just not to `main`. Do not point a preview at a
repo whose branches are protected in a way that blocks this, and remember that preview commits
are visible to everyone with repo access.

## Params

GitHub secrets and variables named `KITSHN_<NAME>` arrive in the container as `<NAME>`.
`KITSHN_VPS_HOST` and `KITSHN_SSH_KEY` are KitSHn's own and are never forwarded.

| Param | Kind | Purpose |
|---|---|---|
| `GITHUB_CLIENT_ID` | variable | OAuth app for user login |
| `GITHUB_CLIENT_SECRET` | secret | same |
| `SESSION_SECRET` | secret | signs session cookies; rotating it logs everyone out |
| `TOKEN_ENCRYPTION_KEY` | secret | encrypts stored user OAuth tokens at rest |
| `DEFAULT_DATA_REPO` | variable | e.g. `Yarden-zamir/budget-joint` |
| `BASE_URL` | variable | public origin, used to build the OAuth callback |

Two OAuth apps are needed, because a callback URL is fixed per app: one for production and one
whose callback is the preview wildcard. Preview builds get the preview app's credentials.

## Pushing To The Data Repo

The app pushes using **the acting user's own GitHub OAuth token**, not a shared deploy key.
GitHub then enforces write access, and a commit is authored by the person who made the change.
Someone removed from the repo loses write access immediately, without the app tracking it.

Tokens are encrypted with `TOKEN_ENCRYPTION_KEY` before being stored, and are only ever
decrypted for the duration of a push.

## Persistence

The KitSHn host data directory is mounted at `/data` in the container, and the app is told so
through `DATA_DIR`. The two are kept as separate names on purpose: one is a host path, the
other is where this process writes. It holds two things:

- `app.db` — SQLite: users, API keys, budget-to-repo mapping. Rebuildable by signing in again;
  losing it loses no budget data.
- `repos/<owner>/<repo>` — the working clone of each data repo. A cache. If it is missing or
  corrupt the app re-clones it.

Neither is a source of truth, so a preview environment starting with an empty data dir is
normal and correct.

## Health

`/healthz` reports process liveness only, so a data-repo outage does not make Docker restart a
container that is serving cached reads. `/readyz` additionally checks that the data repo is
reachable and the branch resolves; that is the one to watch after a deploy.
