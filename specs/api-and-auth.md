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
POST   /budgets/create                       create the repo AND the first budget.yaml
GET    /budgets/{budget}                     identity, members, currency, data branch

GET    /budgets/{budget}/entries             filter by month, person, bucket, tag, payee, kind, unconverted; q= searches
POST   /budgets/{budget}/entries             create; an expense needs a bucket; fx= for another currency
POST   /budgets/{budget}/entries/{id}/convert   add a conversion to an unconverted entry
GET    /budgets/{budget}/entries/{id}
PATCH  /budgets/{budget}/entries/{id}
DELETE /budgets/{budget}/entries/{id}
GET    /budgets/{budget}/entries/{id}/history   commits touching this entry
GET    /budgets/{budget}/entries/{id}/note      long-form markdown note
PUT    /budgets/{budget}/entries/{id}/note      write it; empty text removes the file
GET    /budgets/{budget}/entries/{id}/comments  the conversation, oldest first
POST   /budgets/{budget}/entries/{id}/comments  say something; returns the whole thread
DELETE /budgets/{budget}/entries/{id}/comments/{comment}   only your own
GET    /budgets/{budget}/entries/{id}/attachments          files beside the entry
POST   /budgets/{budget}/entries/{id}/attachments          the file is the body; typed by Content-Type
GET    /budgets/{budget}/entries/{id}/attachments/{name}   the bytes, cached as immutable
DELETE /budgets/{budget}/entries/{id}/attachments/{name}

GET    /budgets/{budget}/buckets                every bucket, with its split
PUT    /budgets/{budget}/buckets/order          reposition several buckets in one commit
PUT    /budgets/{budget}/buckets/{bucket}
POST   /budgets/{budget}/buckets/{bucket}/convert   convert every unconverted entry in one currency here
GET    /budgets/{budget}/rates?currency=&date=  what a unit is worth in the budget currency; commits nothing
GET    /budgets/{budget}/months/{month}         full envelope view: assigned, activity, available
PUT    /budgets/{budget}/months/{month}/assign  assign money to a bucket

GET    /budgets/{budget}/balances            net positions and the suggested settle-up
POST   /budgets/{budget}/settle              record a settlement between two people, in a currency

GET    /budgets/{budget}/members             who can hold a share
PUT    /budgets/{budget}/members             replace the member list
POST   /budgets/{budget}/members/me          add yourself, if you can push to the repo
GET    /budgets/{budget}/collaborators       repo access, including pending invitations
POST   /budgets/{budget}/invite              invite to the data repo AND add as a member

GET    /github/repos                         repos you could connect, flagged for budget.yaml
GET    /github/users?q=                      autocomplete a GitHub login before inviting

GET    /places/nearby?lat=&lon=              venues around a point
GET    /places/search?q=&lat=&lon=           find a venue by name, ranked near you

GET    /budgets/{budget}/history             every change, newest first
GET    /budgets/{budget}/history/{sha}       one change: files, patch, whether it can be undone
POST   /budgets/{budget}/history/undo        revert; defaults to your last un-reverted change
POST   /budgets/{budget}/history/redo        re-apply what your last undo reversed

GET    /budgets/{budget}/scheduled           recurring entry templates
PUT    /budgets/{budget}/scheduled           replace them
GET    /budgets/{budget}/scheduled/due       what is due, default two weeks out
POST   /budgets/{budget}/scheduled/{id}/post turn one due date into an entry

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

`GET /entries` carries `extras`: per entry id, how many comments and attachments hang off it,
only for entries that have any. Two `ls-files` calls, so a list costs nothing proportional
to the ledger. `q` is free text: every word must appear somewhere in the payee, note, tags,
place name or receipt lines. People and amounts are deliberately not searched — a person's
id is on every entry the rules split with them, and "50" would match every entry in the
fifties; the `person` filter and the amount columns are the tools for those.

## Comments And Attachments

A comment thread is returned whole on every write, because it is short by nature and a
client rendering a reply then needs no second round trip — and a reply that crossed with
yours arrives in the same response. Only the author may delete; a comment is attributed
speech, and removing somebody else's words from a shared record is not an edit anyone should
make silently. The author is the acting member, so a placeholder driven through `X-Act-As`
can hold a conversation.

An attachment upload is the file as the request body, not multipart: there is one file per
request, and a multipart envelope would add a parser dependency and a field name for
nothing. The type comes from `Content-Type` when it names one the store accepts, else from
`?media_type=` — the generated TypeScript client sends the schema's `application/octet-stream`
and cannot say more, so it names the type itself. Unsupported types are `unsupported_attachment`;
over the limit is `attachment_too_large` with status 413. Downloads are marked
`immutable`, because the name is a ULID and the same URL never serves different bytes.

A settlement names its `payer`, defaulting to the caller. The person who is *owed* is usually
the one holding the phone when the money arrives, and if their partner does not use the app
nobody could otherwise record it. The caller must be one of the two parties.

## Inviting

Adding a row to `members` never granted anyone access — repo access is the real permission —
so the two had to be done in different places and it was easy to do only one. `POST /invite`
does both: it sends a real GitHub collaborator invitation and adds the person to the member
list, deriving a person id from their login. It reports whether an invitation was actually
created, because GitHub answers 204 when the person already had access.

Both `/github` routes proxy GitHub with the **caller's own token**, so they can only ever
surface what that person can already see. Neither uses a shared credential.

## Places

Proxied so the Google key never reaches a browser, where it could be lifted from the network
tab and spent by anyone. Both routes return the venue's **own coordinates**: a place is where
the place is, and recording the device's position instead filed "the café across the road"
against the pavement outside.

`nearby` answers "what am I standing in". `search` covers everything else — yesterday's lunch,
a shop already left — and only *biases* towards the caller's position rather than restricting
to it, so somewhere across town is still findable. Coordinates are omitted entirely when
unknown.

A place with no name or no position is dropped rather than defaulted; an unnamed pin at 0,0 is
worse than one fewer suggestion. A failed lookup returns an empty list, never an error: a
Places outage must not stop anyone recording an expense.

## Starting And Joining

`POST /budgets` only ever *connected* a repo that already contained a `budget.yaml`, which
meant someone with no budget at all had nowhere to begin: the only way in was hand-writing
YAML on github.com. `POST /budgets/create` is that missing first step. It creates a private
repo (or initializes an empty one the caller names), writes `budget.yaml` with the caller as
sole member, seeds their starter buckets, and links the slug — one call, because every
intermediate state is one the person would otherwise have to be told about. Initializing a
repo that already holds a budget is refused, so a typo cannot overwrite someone's ledger.

`POST /members/me` covers the other direction: you can push to a budget's repo but nobody
added you to `budget.yaml`. Every route that resolves a person answered 403 with "add them to
members in budget.yaml" — including the member editor that would have fixed it. Push access
is the authority the rest of the API already trusts to decide who may change this data, so
refusing to let someone with that access name themselves was the API contradicting itself. It
only ever adds the caller; changing anyone else stays with `PUT /members`, where removal is
checked against the entries that reference them.

`GET /budgets/{budget}` deliberately answers 200 with `me: null` for a non-member rather than
403. A client needs to be able to show who *is* in a budget in order to offer joining it.

## Undo And Redo

Both are `git revert`, so the original stays in history and every undo is itself auditable.

The stack is **replayed from the commits**, never stored: each revert records what it
reverted, so the state survives a restart, is identical on every device, and cannot drift
from the repo. Replaying is necessary rather than fussy — reverting a *redo* is an undo, so
"is the newest commit a revert" would make a second redo silently undo what it had just
restored.

Two stacks, as an editor keeps them: a normal change pushes onto applied and **clears redo**,
an undo moves an entry from applied to redo, and a redo moves it back. Redo is therefore
offered only while your last change was an undo.

A revert that will not apply cleanly is refused rather than discarding the later work built
on it.

`GET /history/{sha}` answers what a change actually did: the files it touched with line
counts, the patch, and whether it is still applied. Two things are decided server-side
because both need the whole log rather than one commit — `reverted_by`, which names the
commit that undid this one, and `can_undo`, which is false once something has. Offering undo
on an already-reverted change would revert the revert, which is redo wearing the wrong label.

The patch is truncated at 400 lines with a flag, rather than streamed. It is read by a person
expanding a row; a longer diff is one they will scroll past, and the flag lets the client say
so instead of silently showing half a change.

## Commit Subjects

A subject is the only description a change ever gets, written once into git at the moment of
the write. Nothing later can recover what it failed to say, so each one is built by comparing
against the previous state rather than restating the request:

- **buckets** — `put_bucket` replaces the whole bucket, so the write itself cannot say whether
  it was a rename, a re-target or a drag. `bucket: yarden fun-money` was the same line for all
  of them. It now reads `bucket: rename Fun money → Bilui, move Bilui to Goals (yarden)`, and
  lists every change rather than picking one, because renaming while dragging is a single
  write.
- **assignments** — the bucket's *name* and the figure it moved from, both read before the
  write destroys them: `assign: Groceries 0.00 → 2000.00 for 2026-08 (yarden)`.
- **members and recurring entries** — replaced as a unit, so the subject names what was added
  or removed: `members: 3 members (added Noa)`. A same-length list with the same names is
  reported as reordered or edited, which is otherwise indistinguishable from nothing
  happening.
- **notes** — the entry's payee, not its ULID.
- **comments and attachments** — `comment: dana on קפה גרג`, `attachment: add
  01K….jpg to קפה גרג`. Both carry an `Entry-Id` trailer so the entry's own history lists
  them.
- **conversions** — `convert: Diner 10.00 USD → 37.00 ILS at 3.7000` for one entry (with
  `Entry-Id`), `convert: 3 USD entries in Transport at 3.5000` for a bucket.

Subjects carry no bidi control characters. Laying out a mixed-script line is the client's
job; the repo is meant to read on its own terms, and a commit message full of invisible
control characters is a worse artefact than one that needs a client to lay it out.

## Errors

One shape everywhere, so clients parse errors once:

```json
{"error": {"code": "shares_do_not_sum", "message": "shares sum to -40.00, entry amount is -50.00",
           "details": {"expected": "-50.00", "actual": "-40.00"}}}
```

FastAPI rejects a malformed body before any route runs, and its own response shape is
`{"detail": [...]}`, not this envelope. That is remapped explicitly — a client reading
`error.message` used to receive an object and render the literal text "[object Object]".

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
