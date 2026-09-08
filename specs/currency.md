# Currency

Behaviour contracts for entries in a currency other than the budget's. Each numbered
requirement is implemented and tested (`tests/test_domain.py::TestCurrency`,
`tests/test_api.py::TestCurrency`, `tests/test_rates.py`); the sections after them explain
why the design has the shape it has.

## Before this

A budget had one `currency` and every entry carried one, defaulted to the budget's. Nothing
read it: every derived figure added `amount` fields together as though they were all in the
budget currency, so a dollar entry recorded through the CLI silently corrupted every total.
That trap is closed: a foreign entry either carries a conversion or is tracked in its own
column, and never leaks into the budget figure.

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
carries `fx` or does not (`Fx` in `money.domain.models`):

```yaml
amount: -120.00          # what the receipt says
currency: EUR
fx:                      # absent = not converted yet
  rate: 4.0250           # budget units per one unit of `currency`
  amount: -483.00        # amount × rate, quantized, in the budget currency
  at: 2026-07-14         # the day the rate belongs to
  source: table | manual
```

`fx.amount` is stored, not recomputed on read, for the same reason `shares` is:
a rate that changed later must not rewrite what an old dinner cost. `rate` has four decimal
places; `fx.amount` has two and is what every derivation reads. The model refuses an
`fx.amount` that is not `amount × rate` quantized — a hand edit that changed one and not the
other is a loud error, on read as well as write. An entry in the budget currency carries no
`fx`; the API refuses a choice for it (`fx_not_needed`).

**CUR-4. `paid_by` and `shares` stay in the entry's own currency.** They sum to `amount`, as
they do today, so the entry is self-consistent whether or not it is converted, and converting
later touches nothing but `fx`. The budget-currency shares are derived on read
(`Entry.budget_shares`): each share is scaled by the rate with `amounts.scale`, and the
rounding drift lands on the largest-magnitude share, so the converted parts sum exactly to
`fx.amount`. The same holds for `paid_by`.

**CUR-5. Three choices at entry time, converting being the default.**

| choice | what is written | when it is right |
|---|---|---|
| convert at today's rate (default) | `fx` from the rate table for the entry date | a card purchase, a normal day abroad |
| convert at a rate I type | `fx` with `source: manual` | the card statement already says what it cost |
| do not convert yet | no `fx` | cash bought earlier, a debt that will be repaid in the same currency |

On the API this is `fx: {mode: table | manual | none, rate?}` on `POST /entries`; omitted
means `table`. The form asks nothing for a budget-currency entry. Choosing another currency
reveals a conversion select with the three choices, the day's rate under it (looked up
without committing), a rate field for `manual`, and a line stating the converted amount.
When no rate can be found the default refuses (`no_rate`, 422) rather than guesses, and the
form disables saving until a rate is typed or *keep for now* is chosen.

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
Foreign figures are never added to the budget-currency figure and never to each other. A
currency that nets to zero is omitted. `GET /entries?unconverted=true` lists what is still
foreign.

**CUR-7. Converting after the fact, per entry.** `POST /entries/{id}/convert` adds `fx` to an
unconverted entry. The rate defaults to the table's rate for the *conversion* day — that is
what "convert it now" means — with `date` to take another day's rate and `rate` to type one.
Converting an entry that already carries `fx` is refused (`already_converted`); undo the
commit instead. Every derived figure moves from `foreign` into the budget-currency column in
the same read. The commit subject is `convert: <payee> 10.00 USD → 37.00 ILS at 3.7000` and
carries the `Entry-Id` trailer, so it appears in the entry's history as kind `convert`.

**CUR-8. Converting after the fact, per bucket.** `POST /buckets/{id}/convert` with a
`currency` converts every unconverted entry in that currency with a share in the bucket, at
one rate, in **one commit** — `convert: 3 USD entries in Transport at 3.5000`. An entry whose
shares span two buckets is converted whole, because an entry has one `fx`; the response's
`spanning` lists them so the person knows the other bucket moved too, and the web panel says
so before closing. Converting a whole budget is this call over each bucket and needs no route
of its own. The chip on a bucket row is the way in.

**CUR-9. The rate table is committed.** `rates.yaml` at the repo root holds daily rates the
app fetched, keyed by date and currency:

```yaml
2026-07-14:
  EUR: 4.0250
  USD: 3.7100
```

The API fetches a rate only when a conversion needs one the table lacks, and commits the row
in the same commit as the conversion (`rate_row` through `add_entry`, `post_scheduled` and
`convert_entries`). A manual rate is written on the entry only, never into the table: the
table is what the provider said, not what a person chose. It exists so a repo is reproducible
offline and so two people converting the same day get the same rate. `GET /rates?currency=&date=`
answers from the table, else the provider, and commits nothing — the form shows what a
conversion would do without leaving a row nothing depends on.

**CUR-10. One provider, replaceable.** The European Central Bank publishes daily reference
rates with no key and no terms that matter for a household. It is the provider
(`money.api.rates.fetch_rate`), and any pair is a cross through the euro. A weekend or
holiday takes the last published day before it, which is what the card does too. The
provider is behind one function returning `Decimal | None`, so a failed fetch degrades to
"type the rate, or keep it unconverted", never to a guess and never to a blocked save. The
parser is tested against a saved feed; the suite never touches the network.

**CUR-11. Changing the budget currency is a migration, not a setting.** Every stored
assignment and target, and every `fx.amount`, is in the budget currency. Flipping
`budget.yaml` alone would corrupt all of it. No route or screen changes it; a future
`money budget recurrency` command may rewrite the repo in one commit, and is not built.

**CUR-12. Display shows the budget figure first, foreign beside it.** A row shows the
budget-currency figure in the amount column and the original beneath it: `€120.00 · rate
4.025`. An unconverted row shows its own currency in the amount column and a *convert* action
in the detail panel. A bucket or balance with foreign money shows a chip per currency after
its figure — `−$5.00 unconverted` — and the chip is the way into converting the bucket. The
month summary's ready-to-assign does the same.

**CUR-13. Settlements are per currency.** Debt is folded in whatever currency it is in
(CUR-6), so a settle-up suggests one transfer per currency and `POST /settle` takes the
`currency` the money changed hands in. A foreign settlement is recorded **unconverted on
purpose**: it clears that currency's column, and converting it would move the payment into
the shekel column while the debt it paid stayed in dollars. Repaying a dollar debt in shekels
is: convert the entries (CUR-7 or CUR-8), then settle in shekels.

**CUR-14. Income and funding.** Foreign income that is not converted is foreign
ready-to-assign (`MonthResponse.foreign`), shown as *not yet assignable*; it cannot fund an
envelope until it is converted, because assignments and targets are in the budget currency.
Converting an income entry moves it into the pool. A scheduled template carries a currency
and a `convert` flag: posted with it on, the entry converts at the posting day's rate; off,
it stays unconverted. There is no manual rate on a template, because the rate belongs to the
day it is posted.

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

## Where it lives

| concern | code |
|---|---|
| the `fx` block, `budget_shares`, `budget_paid_by`, `foreign` | `money.domain.models.Entry` |
| proportional scaling with exact sums | `money.domain.amounts.scale` |
| per-currency columns on balances, buckets, months | `money.domain.derive` |
| rate table, conversion commits | `money.store.store` (`RATES_PATH`, `convert_entries`) |
| resolving a rate: typed, table, provider | `money.api.fx` |
| the ECB parser and fetch | `money.api.rates` |
| routes | `entries.py` (`fx`, `convert`, `unconverted`), `budgets.py` (`rates`, bucket convert, settle currency), `scheduled.py` |
| the chips and both convert panels | `components/Foreign.tsx`, `features/Convert.tsx` |

## Deliberately not built

- **Live revaluation.** An unconverted balance is shown in its own currency, never as an
  estimated budget figure. A converted one does not move when the market does.
- **Per-person currencies.** One person keeping their envelopes in dollars inside a shekel
  household is a second unit of account for *assignments*, and every derived figure would
  need two answers. Out of scope; the fix is a second budget.
- **Partial conversion.** An entry converts whole. Splitting "convert half of it" is two
  entries.
- **Un-converting.** `fx` is written by one commit; undo that commit.
