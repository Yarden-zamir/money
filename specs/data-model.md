# Data Model

The budget data lives in a private git repo, one repo per budget. The app never invents a
storage format of its own: what is committed *is* the state, and it is meant to be read and
edited by a person with a text editor and `git log` even if this app disappears.

SQLite holds only app state that is not budget data: users, API keys, and which repo backs
which budget. Losing the SQLite file loses no budget data.

## Repo Layout

```
budget.yaml                        # budget identity, members, currency
rules.yaml                         # default split rules
people/<person>/buckets.yaml       # that person's envelopes
people/<person>/assignments/2026-07.yaml
ledger/2026-07.yaml                # entries, one file per month
scheduled.yaml                     # recurring entries, optional
notes/<entry-id>.md                # long-form note for one entry, optional
README.md                          # generated; explains this layout to a human
.money/schema-version              # integer, currently 1
```

Person ids are lowercase slugs (`yarden`, `dana`), not GitHub logins. `budget.yaml` maps
GitHub logins onto person ids, so a person keeps their identity if they rename on GitHub.

Membership and access are different things. `members` decides who can hold a share of an
entry; GitHub repo access decides who can read or write the budget at all. Someone listed as
a member without repo access simply never signs in. Removing a member is refused while any
entry still references them, because dropping them would orphan those shares and silently
change every balance.

Someone who *can* push but is not yet in `members` may add themselves — the one exception to
membership being edited only as a whole list. Push access already decides who may change this
data, so making them wait for another member to type their name in was a wall with no
security value behind it.

A new person always arrives with buckets. Creating a budget and joining one both write
`people/<person>/buckets.yaml` in the same commit as the `budget.yaml` change, because
buckets are per-person: someone added without them lands in a budget they can read and
cannot file anything under. The seeded set (`money.domain.starter`) is a handful of buckets
across four groups, with no targets — a target is a claim about what that person intends to
spend, and guessing it would put a number on screen nobody chose.

## Entries

An entry is one real-world event. Every entry answers two independent questions:

- **Who paid?** `paid_by` — actual cash movement, per person.
- **Who bears it, and out of which envelope?** `shares` — cost attribution, per person and
  bucket.

Keeping these separate is what makes the app both YNAB-like and Splitwise-like from a single
record. Debt is not stored, it is the difference between the two.

```yaml
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
  note: coffee for both
  tags: [coffee]
  rule: split-5050
```

That entry is the user's worked example: Yarden fronts 50, both people book 25 against their
own `fun-money` envelope, and Dana ends up owing Yarden 25 — derived, never written down.

### Field Rules

- `amount` is negative for outflow, positive for inflow. It is the total of the event.
- `paid_by` values must sum to `amount`. `shares` amounts must sum to `amount`. Both are
  checked on write and on read; a file that violates this is a hard error, not a warning.
- Money is `Decimal`, serialized as a plain string with 2 decimal places. Never a float.
- `bucket` may be `null` for entries that move money without consuming an envelope
  (`income`, `transfer`, `settlement`). It is required for `kind: expense`.
- `id` is a ULID: sortable by creation, stable across edits, and usable as a filename.
- `date` and `at` answer different questions. `date` is an accounting decision — which day,
  and so which budget month, this belongs to — and a person may back-date it. `at` is the
  wall-clock moment it happened, recorded automatically, and is what time-of-day patterns
  read. Collapsing them would mean a back-dated entry claiming to have happened at midnight.
  `at` is naive local time on purpose: which day a purchase belongs to is a local human
  judgement, and converting through a timezone could land a late-night purchase in the wrong
  budget month.
- `rule` records which rule produced the split. It is an audit trail, not an instruction —
  changing a rule never rewrites existing entries.

### Kinds

| kind | meaning | bucket |
|---|---|---|
| `expense` | money left the household | required on every share |
| `income` | money arrived, becomes ready-to-assign for that person | must be `null` |
| `transfer` | between accounts of the same person, budget-neutral | must be `null` |
| `settlement` | one person pays another back, clears debt | must be `null` |

A settlement is an ordinary entry: Dana hands Yarden 25, so `paid_by: {dana: -25.00}` and a
single share of `-25.00` to Yarden. It moves both net positions and touches no envelope.

## Derived Values

Nothing below is stored. All of it is folded from the ledger on read, which is what the user
asked for: balances stay consistent with history by construction.

- **Net position** of person P = `sum(shares[P].amount) - sum(paid_by[P])` over all entries.
  Positive means the household owes them: they bore less than they paid out. In the coffee
  example Yarden is `-25 - (-50) = +25` and Dana is `-25 - 0 = -25`, so Dana owes Yarden 25.
- **Pairwise debt** — with two people it is one number. With three or more, net positions are
  settled greedily into the fewest transfers. Greedy is not always minimal; that is
  acceptable while budgets stay small. Revisit if a budget ever exceeds ~8 people, where the
  extra transfer becomes noticeable.
- **Bucket activity** for person P, bucket B, month M = sum of that person's shares on B in M.
- **Bucket available** = carryover from prior month + assigned this month + activity, where
  activity is already negative for spending. Carryover is computed by folding every month
  from the budget's start; there is no stored opening balance to drift.
- **Ready to assign** for P = their income to date − everything they have assigned.

## Buckets And Assignment

Buckets belong to a person, not to the budget. That is deliberate: in a joint budget Yarden
and Dana each keep their own envelopes and their own income, and each assigns their own money.
Two people can hold buckets with the same id; they are still separate envelopes.

```yaml
# people/yarden/buckets.yaml
- id: fun-money
  name: בילויים
  group: lifestyle
  target:
    kind: monthly
    amount: 400.00
```

```yaml
# people/yarden/assignments/2026-07.yaml
fun-money: 400.00
groceries: 1200.00
```

Assignment files are a flat map so a person can edit them by hand without touching the app.

## Recurring Entries

`scheduled.yaml` holds templates: rent, a salary, a subscription. Each carries the same
two-sided split an entry does, plus a recurrence — weekly on a weekday, monthly on a day,
yearly on a month and day, each with an optional interval.

**A recurrence never posts by itself.** It produces a list of dates that are *due*, and a
person turns each one into an entry. Auto-posting would put money in a budget with no author
and nobody watching, which is exactly what the git-backed history exists to prevent.

- `last_posted` is written only by posting, never by editing a template. The entry and the
  marker land in **one commit**: if the entry saved and the marker did not, the same charge
  would be offered again and posted twice.
- A monthly recurrence on day 31 falls on the last day of shorter months. Rolling into the
  next month instead would move the charge into the wrong budget month.
- A template with no explicit split falls back to the rules at post time, so it stays correct
  as the rules change. One with a split keeps it. An expense must name a bucket or carry a
  split — checked when the template is written, not weeks later when the charge falls due.

## Receipts

An entry may carry `items`, the lines of a receipt. One payment buys several things and they
do not always belong in the same envelope — a supermarket run is groceries and a bottle of
wine, which the entry-level split cannot express.

Lines must sum to the entry. When they carry their own splits, every line must carry one and
their total per person and bucket must equal the entry's split: two numbers that disagree,
with nothing to say which is right, is worse than having no detail at all.

## Location

An entry may record where it happened: coordinates, plus the venue name when one was chosen.

🔴 This is a deliberate trade. Committing coordinates makes suggestions work on every device
and survive clearing a browser, and it also means the repo holds a durable, shared,
git-versioned record of where you have been — readable by every collaborator, and present in
history even after a later edit removes it.

Venue names come from a places lookup proxied through the backend, so the API key never
reaches a browser. It is called only while someone is adding an entry, never in the
background.

## Notes

An entry's `note` field is a one-liner. Anything longer lives in `notes/<entry-id>.md` as
markdown: a paragraph explaining why a split is uneven belongs somewhere a diff shows line by
line, and somewhere a person can read without picking it out of YAML. Writing an empty note
deletes the file rather than leaving an empty one.

## Schema Version

`.money/schema-version` holds an integer, currently `1`. It is written on the first change the
app makes to a repo, so a repo created by hand gains one.

The app refuses to write to a repo whose version is **higher** than it understands. Reading
such a repo might appear to work while silently dropping fields the older code cannot see, and
the next write would then delete them.

## Rules

Rules supply default splits and buckets when an entry is created. First match wins, which is
the same resolution order KitSHn uses for `.kitshn.yaml`, so the two configs behave alike.

```yaml
- id: yarden-hobby
  when: {tag: hobby}
  split: {yarden: 1.0}
  bucket: {yarden: hobbies}

- id: groceries
  when: {payee_contains: שופרסל}
  split: {yarden: 0.5, dana: 0.5}
  bucket: {yarden: groceries, dana: groceries}

- id: split-5050
  when: {}
  split: {yarden: 0.5, dana: 0.5}
```

`when` supports `payee_contains`, `tag`, `paid_by`, and `min_amount`. An empty `when` matches
everything and is how a catch-all default is written. `split` ratios must sum to 1.

Rules run only at creation time and only when the caller does not supply an explicit split.
Rounding sends the remaining agorot to the largest share, so splits always sum exactly.

## Git As The History Layer

- One mutation is one commit. There is no batching that would hide a change from `git log`.
- Commit **author** is the person who made the change, using their GitHub name and email, so
  `git shortlog` and `git blame` attribute correctly. Committer is the app.
- Commit subject is human-first, with machine detail in trailers:

  ```
  entry: add קפה גרג 50.00 ILS

  Entry-Id: 01K9VYQ2N3X8R4T7B0M6D5C1FA
  Budget: joint
  Actor: Yarden-zamir
  ```

- Entry history is `git log` scoped to the ledger file, filtered by `Entry-Id`. The API
  exposes it directly, so "what changed and who changed it" needs no audit table.
- Closing a month is an annotated tag, `close/2026-07`, naming the commit the month ended on,
  so it can be checked out exactly as it stood. It is a bookmark, not a lock: later edits to
  a closed month are still allowed, because refusing them would mean the app deciding a
  correction is illegitimate.
- Writes take a per-repo lock, commit, then push. A rejected push is retried after
  `pull --rebase`. Ledger entries are kept sorted by `(date, id)` so two people appending on
  the same day produce a clean rebase instead of a conflict.

## Branch Per Environment

The data branch is supplied by config, not derived. Production uses `main`. A KitSHn PR
preview passes its environment name as the branch, and the app creates that branch from
`main` on first use. Previews therefore run against real data shapes without ever writing to
`main`, and deleting the preview branch discards the preview's writes.
