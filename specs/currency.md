# Currency

A plan, not a description of shipped behaviour. Nothing below is implemented; each numbered
requirement is the contract a future change must satisfy, and the sections after them explain
why the plan has the shape it has.

## What exists today

- A budget has one `currency` in `budget.yaml`.
- Every entry carries a `currency` field, defaulted to the budget's. Nothing reads it: every
  derived figure — balances, bucket activity, ready-to-assign — adds `amount` fields together
  as though they were all in the budget currency.
- The web form has no currency field. The CLI accepts `--currency` and the API accepts
  `currency`, so an entry in a second currency can already be recorded, and it silently
  corrupts every total.

That last point is the reason this needs a plan rather than a feature flag: the field is a
trap until the arithmetic honours it.

## The problem, stated once

A household budget is kept in one currency. A trip abroad, an online purchase, a salary paid
in dollars — these arrive in another. Three things are true at once:

- **Envelopes and balances need one unit** or "can we afford dinner" has no single answer.
- **The receipt figure must survive** — that is what the bank statement will show.
- **The rate depends on when you convert.** The card charges at settlement, cash was bought
  last week, and a debt paid back in dollars was never converted at all. Converting at a
  single moment nobody chose is a guess dressed up as a fact.

So conversion is a *decision*, made at entry time by default, and deferrable. An entry that
has not been converted stays in its own currency, inside the same bucket and the same
balance, as a second column. A bucket can hold **+100 shekels and −5 dollars** at the same
time, and the dollars stay dollars until somebody converts them — per entry, or a whole
bucket at once.

## Requirements

**CUR-1. The budget currency is the unit of account for converted money.** Every derived
figure — balances, settle-up, bucket assigned/activity/available, ready-to-assign, group
subtotals — has one figure in the budget currency, made of entries in that currency plus
converted entries. Unconverted entries never contribute to it.

**CUR-2. The original is never lost.** An entry keeps `amount` and `currency` exactly as
recorded. Conversion adds fields; it does not replace them.

**CUR-3. Conversion is a stored block on the entry.** An entry in a foreign currency either
carries `fx` or does not:

```yaml
amount: -120.00          # what the receipt says
currency: EUR
fx:                      # absent = not converted yet
  rate: 4.0250           # budget units per one unit of `currency`
  amount: -483.00        # amount × rate, quantized, in the budget currency
  at: 2026-07-14         # the day the rate belongs to
  source: table | manual
```

`fx.amount` is stored, not recomputed on read, for the same reason `shares` and `rule` are:
a rate that changed later must not rewrite what an old dinner cost. `rate` has four decimal
places; `fx.amount` has two and is what every derivation reads.

**CUR-4. `paid_by` and `shares` stay in the entry's own currency.** They sum to `amount`, as
they do today, so the entry is self-consistent whether or not it is converted, and converting
later touches nothing but `fx`. The budget-currency shares are derived on read: `fx.amount`
is allocated across the shares in their own proportions with `allocate`, so the converted
parts sum exactly to `fx.amount` and the rounding lands on the largest share. The same holds
for `paid_by`.

**CUR-5. Three choices at entry time, converting being the default.**

| choice | what is written | when it is right |
|---|---|---|
| convert at today's rate (default) | `fx` from the rate table for the entry date | a card purchase, a normal day abroad |
| convert at a rate I type | `fx` with `source: manual` | the card statement already says what it cost |
| do not convert yet | no `fx` | cash bought earlier, a debt that will be repaid in the same currency |

The form asks nothing for a budget-currency entry. Choosing another currency reveals the rate,
pre-filled from the table, with *keep in EUR for now* beside it.

**CUR-6. Unconverted money is tracked per currency, in the same places.** Every derived
figure that has a budget-currency number also has `foreign`, a map of currency to amount for
whatever is unconverted:

```yaml
bucket: groceries
available: 100.00                # ILS, the household's figure as today
foreign: {USD: -5.00}            # spent against this bucket, not yet converted
```

The same shape on balances (`net` plus `foreign`), on settle-up (one suggested transfer per
currency), on the month summary (`ready_to_assign` plus `foreign`), and on group subtotals.
Foreign figures are never added to the budget-currency figure and never to each other.

**CUR-7. Converting after the fact, per entry.** `POST /entries/{id}/convert` adds `fx` to an
unconverted entry. The rate defaults to the table's rate for the *conversion* day — that is
what "convert it now" means — with `date` to take another day's rate and `rate` to type one.
Converting an entry that already carries `fx` is refused; undo the commit instead. Every
derived figure moves from `foreign` into the budget-currency column in the same read.

**CUR-8. Converting after the fact, per bucket.** `POST /buckets/{id}/convert` with a
`currency` converts every unconverted entry in that currency with a share in the bucket, at
one rate, in **one commit** — the subject names the bucket, the currency, the rate and the
count. An entry whose shares span two buckets is converted whole, because an entry has one
`fx`; the response lists any such entries so the person knows the other bucket moved too.
Converting a whole budget is this call over each bucket and needs no route of its own.

**CUR-9. The rate table is committed.** `rates.yaml` at the repo root holds daily rates the
app fetched, keyed by date and currency:

```yaml
2026-07-14:
  EUR: 4.0250
  USD: 3.7100
```

The API fetches a rate only when a conversion needs one the table lacks, and commits the row
in the same commit as the conversion. A manual rate is written on the entry only, never into
the table: the table is what the provider said, not what a person chose. It exists so a repo
is reproducible offline and so two people converting the same day get the same rate.

**CUR-10. One provider, replaceable.** The European Central Bank publishes daily reference
rates with no key and no terms that matter for a household. It is the first provider. The
provider is behind one function returning `Decimal | None`, so a failed fetch degrades to
"type the rate, or keep it unconverted", never to a guess and never to a blocked save.

**CUR-11. Changing the budget currency is a migration, not a setting.** Every stored
assignment and target, and every `fx.amount`, is in the budget currency. Flipping
`budget.yaml` alone would corrupt all of it, so the field is read-only in the UI and the CLI
refuses to change it. A future `money budget recurrency` command may rewrite the repo in one
commit; it is not part of this plan.

**CUR-12. Display shows the budget figure first, foreign beside it.** A row shows the
budget-currency figure in the amount column and the original beneath it: `€120.00 · rate
4.025`. An unconverted row shows its own currency in the amount column and a *convert* action
in the detail panel. A bucket or balance with foreign money shows a chip per currency after
its figure — `−$5.00 unconverted` — and the chip is the way into converting the bucket. The
month summary's ready-to-assign does the same.

**CUR-13. Settlements are per currency.** Debt is folded in whatever currency it is in
(CUR-6), so a settle-up suggests one transfer per currency and a settlement entry names the
currency it was paid in. Repaying dollars with dollars never touches a rate. Repaying a dollar
debt in shekels is: convert the entries (CUR-7 or CUR-8), then settle in shekels.

**CUR-14. Income and funding.** Foreign income that is not converted is foreign
ready-to-assign; it cannot be assigned to an envelope until it is converted, because
assignments and targets are in the budget currency. Converting an income entry moves it into
the pool. Scheduled entries carry a currency and, when posted, take the same three choices
an entry does, with the template remembering which.

**CUR-15. Rounding follows `allocate`.** `fx.amount` is quantized to two places with
`ROUND_HALF_UP`. Converted shares are allocated from it, never rounded individually, so they
sum exactly. A conversion is reproducible from `amount` and `rate` alone.

## Why unconverted money stays inside the bucket

The alternative was a holding area — an "uncoverted" pseudo-bucket, or a separate screen —
which answers the accounting question and loses the budgeting one. Five dollars spent on
groceries *is* groceries spending; the envelope should know about it even before anyone
knows what it cost in shekels. Keeping it as a second column in the same row means the
bucket says "100 shekels, and also five dollars you have not converted", which is the true
state, rather than "100 shekels" with the dollars filed somewhere else.

Never adding the two columns is the rule that keeps this honest. The moment a foreign figure
is folded into the budget figure at an assumed rate, the app is back to guessing.

## Order of work

1. Model and validation (CUR-2, CUR-3, CUR-4, CUR-15). Until this lands the API rejects
   `currency` other than the budget's, so the trap described above closes first.
2. Derivations: budget-currency figures read through `fx.amount`; unconverted entries
   accumulate into `foreign` (CUR-1, CUR-6). `test_domain.py` covers a mixed ledger against
   hand-computed totals, including a bucket that is positive in one currency and negative in
   another.
3. The rate table and the ECB provider (CUR-9, CUR-10), fetch mocked in tests.
4. Conversion routes (CUR-7, CUR-8), each one commit, with history subjects.
5. The form's three choices and the rows and chips (CUR-5, CUR-12), screenshotted in both
   languages — a currency symbol is exactly the kind of thing that lands on the wrong side in
   Hebrew.
6. Settlement per currency, income and scheduled (CUR-13, CUR-14).

## Deliberately not planned

- **Live revaluation.** An unconverted balance is shown in its own currency, never as an
  estimated budget figure. A converted one does not move when the market does.
- **Per-person currencies.** One person keeping their envelopes in dollars inside a shekel
  household is a second unit of account for *assignments*, and every derived figure would
  need two answers. Out of scope; the fix is a second budget.
- **Partial conversion.** An entry converts whole. Splitting "convert half of it" is two
  entries.
- **Un-converting.** `fx` is written by one commit; undo that commit.
