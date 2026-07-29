# API And Auth

The HTTP API is the product. The web app and the CLI are both clients of it and get no
private endpoints, so anything the UI can do is scriptable.

## Identity

GitHub is the only identity provider. There are no local passwords to store or reset.

| Client | Credential | How it is obtained |
|---|---|---|
| Web app | Signed session cookie | GitHub OAuth web flow |
| CLI, scripts | `Authorization: Bearer money_pat_…` | `money auth login`, or the web UI |

API keys are shown once at creation and stored only as a SHA-256 hash, so a leaked database
does not yield usable tokens. Each key carries a name, optional expiry, and scopes
(`read`, `write`, `admin`). `last_used_at` is updated on use so stale keys are visible.

`money auth login` uses the GitHub **device flow**, matching `gh auth login`: the CLI prints
a code, the user approves in a browser, and the CLI exchanges it for an API key it stores in
`~/.config/money/hosts.yaml`. No secret is ever pasted into a terminal.

### Signing In To A PR Preview

A GitHub OAuth app has exactly one callback URL, so a preview at `pr.42.money.yarden-zamir.com`
cannot run its own flow. Production runs it and hands the result back:

```
pr-42  GET /auth/config           -> login_url points at production, carrying return_host
prod   GET /auth/github/start?return_host=pr.42.money.yarden-zamir.com
prod   GET /auth/github/callback  -> mints a handoff ticket instead of a session
pr-42  GET /auth/handoff?ticket=  -> validates, creates the user, sets its own cookie
```

The ticket carries the user's GitHub token, so it is deliberately hostile to reuse: signed
with the shared `SESSION_SECRET`, valid for 60 seconds, single-use via a nonce the preview
records, and pinned to one hostname that the preview re-checks against its own. The token
inside is encrypted with `TOKEN_ENCRYPTION_KEY` rather than carried in the clear.

`return_host` is checked against `pr.<digits>.<production host>`, built from parts rather
than pattern-matched. It decides where a ticket is delivered, so a generous check here would
be an open redirect that leaks a credential. `tests/test_preview_auth.py` pins that down.

🔴 The ticket travels in a URL and therefore reaches browser history. The 60 second window is
the mitigation; widening it invalidates the trade.

## Authorization

Access to a budget is GitHub repo access to the repo backing it. The app does not maintain
its own sharing model — sharing a budget means adding a collaborator on GitHub, and revoking
means removing them there.

- `push` access on the backing repo → read and write the budget.
- `pull` access only → read.
- No access → the budget is invisible; requests 404 rather than 403, so the API does not
  confirm that a repo exists to someone who cannot see it.

Collaborator checks are cached for 5 minutes per (user, repo). The cache is a latency
measure, not a security boundary. Revocation therefore takes effect within 5 minutes;
shorten the TTL if that ever proves too slow.

## Endpoints

All paths are under `/api/v1`. Money is a decimal string; dates are ISO-8601.

```
GET    /budgets                              list budgets the caller can see
POST   /budgets                              connect an existing GitHub repo as a budget
GET    /budgets/{budget}                     identity, members, currency, data branch

GET    /budgets/{budget}/entries             filter by month, person, bucket, tag, payee
POST   /budgets/{budget}/entries             create; applies rules unless split is given
GET    /budgets/{budget}/entries/{id}
PATCH  /budgets/{budget}/entries/{id}
DELETE /budgets/{budget}/entries/{id}
GET    /budgets/{budget}/entries/{id}/history   commits touching this entry

GET    /budgets/{budget}/buckets                buckets for a person
PUT    /budgets/{budget}/buckets/{bucket}
GET    /budgets/{budget}/months/{month}         full envelope view: assigned, activity, available
PUT    /budgets/{budget}/months/{month}/assign  assign money to a bucket

GET    /budgets/{budget}/balances            net positions and the suggested settle-up
POST   /budgets/{budget}/settle              record a settlement between two people

GET    /budgets/{budget}/members             who can hold a share
PUT    /budgets/{budget}/members             replace the member list

GET    /budgets/{budget}/rules
PUT    /budgets/{budget}/rules
POST   /budgets/{budget}/rules/preview       what would this entry split into? no write

GET    /me
GET    /me/keys      POST /me/keys      DELETE /me/keys/{id}

GET    /auth/config                          where sign-in starts for this deployment
GET    /auth/github/start                    begin the browser flow, optional return_host
GET    /auth/github/callback                 OAuth callback; production only
GET    /auth/handoff                         accept a preview sign-in ticket; previews only
POST   /auth/device/start   POST /auth/device/poll     CLI sign-in
POST   /auth/logout

GET    /healthz                              liveness; does not touch the data repo
GET    /readyz                               liveness plus data-repo reachability
```

`POST /entries` returns the created entry **and** the commit sha that recorded it, so a client
can link straight to the diff.

## Errors

One shape everywhere, so clients parse errors once:

```json
{"error": {"code": "shares_do_not_sum", "message": "shares sum to -40.00, entry amount is -50.00",
           "details": {"expected": "-50.00", "actual": "-40.00"}}}
```

Validation that money adds up runs on write **and** on read. A hand-edited ledger file that
does not balance surfaces as a loud error naming the file and entry, never as a silently
wrong total.

## Concurrency

Writes to one budget are serialized by a per-repo lock, so two requests cannot interleave a
read-modify-write on the same ledger file. If the push is rejected because someone committed
in the meantime, the app rebases and retries once, then fails with `data_repo_conflict`
rather than forcing anything.

## Generated Clients

The OpenAPI schema is the single source both clients come from:

- TypeScript for the web app, via `@hey-api/openapi-ts`. Checked in, regenerated by
  `pnpm run generate:api`, and CI fails if regenerating produces a diff — a backend change
  that breaks the frontend fails at build time, not in the browser.
- Python for the CLI, generated from the same schema. See [CLI](cli.md).

Every route sets an explicit `operation_id`, because generated client method names are a
public interface and FastAPI's default derived names change whenever a path changes.
