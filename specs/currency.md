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
in dollars — these arrive in another. Two people then need two answers from the same record:

- **What did it cost us, in our money?** The budget question. Envelopes and balances are in
  the budget currency and must stay so, or "can we afford dinner" has no single answer.
- **What did the receipt say?** The audit question. The original amount and currency must
  survive unchanged, because that is what the bank statement will show.

Splitwise stores both and converts at a rate it fetches. YNAB converts nothing and keeps one
currency per budget, which pushes the problem onto the person. This plan takes Splitwise's
answer with one difference: the rate is chosen and committed, never fetched silently.

## Requirements

**CUR-1. The budget currency is the unit of account.** Every derived figure — balances,
settle-up, bucket assigned/activity/available, ready-to-assign, group subtotals — is in the
budget currency and nothing else. An entry in another currency contributes its converted
value, never its face value.

**CUR-2. The original is never lost.** An entry keeps `amount` and `currency` as they were
recorded. Conversion adds fields; it does not replace them.

**CUR-3. The rate is stored on the entry, at creation.** An entry in a foreign currency
carries:

```yaml
amount: -120.00          # what the receipt says
currency: EUR
fx:
  rate: 4.0250           # budget units per one unit of `currency`
  amount: -483.00        # amount × rate, quantized, in the budget currency
  source: manual | ecb | override
```

`fx.amount` is stored, not recomputed on read, for the same reason `shares` and `rule` are:
a rate that changed later must not rewrite what an old dinner cost. `rate` has four decimal
places; `fx.amount` has two and is what every derivation reads.

**CUR-4. `paid_by` and `shares` are in the budget currency.** They sum to `fx.amount`, not to
`amount`. The balance and envelope arithmetic then needs no branch: an entry with `fx` is
read through `fx.amount`, and one without is read through `amount`, and the invariant "both
halves sum to the entry's budget-currency total" holds everywhere. The model validator
enforces it on read as well as write, as it does today.

**CUR-5. Rates come from a committed table, with a manual override.** `rates.yaml` at the
repo root holds daily rates the app fetched, keyed by date and currency:

```yaml
2026-07-14:
  EUR: 4.0250
  USD: 3.7100
```

The API fetches a rate only when an entry in a foreign currency is being created and the
table has none for that date, and commits the row in the same commit as the entry. A person
can type a rate instead — the one on the card statement is the true one — and that sets
`source: override`. The table exists so a repo is reproducible offline and so two people
entering the same day's purchases get the same rate.

**CUR-6. One provider, replaceable.** The European Central Bank publishes daily reference
rates with no key and no terms that matter for a household. It is the first provider. The
provider is behind one function returning `Decimal | None`, so a failed fetch degrades to
"type the rate", never to a guess and never to a blocked save.

**CUR-7. The form asks for the currency only when it differs.** The amount field keeps its
one-number contract. A currency picker sits beside it, defaulting to the budget currency and
showing the recent foreign ones first. Choosing another currency reveals the rate field,
pre-filled from the table when one exists, and a line stating the converted amount before
the save — the same place the split summary sits.

**CUR-8. Display shows both, converted first.** A row shows the budget-currency figure in the
amount column, and the original beneath it in the muted line: `€120.00 · rate 4.025`. The
ledger stays scannable in one currency; the receipt figure is one glance away.

**CUR-9. Settlements are in the budget currency.** Debt is folded in the unit of account
(CUR-1), so it is settled in it. Someone who repays in cash abroad records a settlement in
the budget currency at the rate they agreed. Cross-currency settlement is out of scope until a
household asks for it.

**CUR-10. Multi-currency income.** A salary in dollars is an income entry with `fx`, so
ready-to-assign is in the budget currency like everything else. Scheduled entries carry a
currency and their posting resolves a rate exactly as a hand-entered entry does.

**CUR-11. Changing the budget currency is a migration, not a setting.** Every stored
`paid_by`, `shares`, assignment and target is in the old currency. Flipping `budget.yaml`
alone would corrupt all of it, so the field is read-only in the UI and the CLI refuses to
change it. A future `money budget recurrency` command may rewrite the repo in one commit; it
is not part of this plan.

**CUR-12. Rounding follows `allocate`.** `fx.amount` is quantized to two places with
`ROUND_HALF_UP`, then split with the existing `allocate`, so the shares sum exactly to the
converted total and the remainder lands on the largest share as it does today.

## Order of work

1. Model and validation (CUR-2, CUR-3, CUR-4, CUR-12). The API rejects `currency` other than
   the budget's until this lands, so the trap described above closes first.
2. Derivations read through `fx.amount` (CUR-1). Tests in `test_domain.py` cover a mixed
   ledger against hand-computed totals.
3. The rate table and the ECB provider (CUR-5, CUR-6), with the fetch mocked in tests.
4. The form and the row (CUR-7, CUR-8), screenshotted in both languages — a currency symbol
   is exactly the kind of thing that lands on the wrong side in Hebrew.
5. Scheduled and income (CUR-10). Settlement stays as it is (CUR-9).

## Deliberately not planned

- **Live revaluation.** Balances do not move when the market does. A debt of 483 is 483
  until it is paid; if that ever feels wrong, it is CUR-9 that needs revisiting, not CUR-3.
- **Per-person currencies.** One person keeping their envelopes in dollars inside a shekel
  household is a second unit of account, and every derived figure would need two answers.
  Out of scope; the fix is a second budget.
- **Historical rates for back-dated entries.** CUR-5 keys the table by the entry's `date`, so
  a back-dated entry asks for that date's rate. Nothing more is needed.
