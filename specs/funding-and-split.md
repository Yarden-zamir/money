# Funding And Split

How much you put into a bucket and how much of its spending you bear are two different
decisions. The app used to conflate them: buckets were per-person lists, and the split came
from a rules file keyed by payee.

- **Funding** — "how much am I putting into this envelope this month". A cashflow decision,
  per person, per bucket, per month.
- **Split** — "whose expense is this really". A fairness decision, fixed on the bucket,
  independent of who funded it or who paid.

A bucket is one shared thing that several people fund and anyone can spend against. A
person's position in it is `funded − borne`, and **a bucket can be in the red for one person
while another is in the black** — the YNAB red bar, per person rather than per envelope.

## Shape

```yaml
# buckets.yaml — at the repo root, one definition shared by everyone
- id: rent
  name: Rent
  group: Essentials
  split: {yarden: 0.5, dana: 0.5}      # who bears spending here
  target: {kind: monthly, amount: 6400}
```

```yaml
# people/yarden/assignments/2026-08.yaml — unchanged
rent: 2000.00                           # what I put in
```

An **empty split means "evenly, among whoever is a member"**, resolved on read rather than
stored. Adding somebody to the budget would otherwise leave every unconfigured bucket quietly
attributing their spending to everyone else. A *partial* split is refused rather than
normalised: shares summing to 0.9 are a typo, and scaling them to 1 would attribute money in
proportions nobody chose.

Rules stop being about people, which is the simplification that falls out of this. A rule
carried `split` and a per-person `bucket` map; with one shared bucket that owns its split, a
rule is pure categorisation:

```yaml
- id: groceries
  when: {payee_contains: שופרסל}
  bucket: food                          # which envelope. the envelope decides who bears it.
```

## Derivation

Three recorded quantities, two derived comparisons. Nothing new is stored.

| recorded | where |
|---|---|
| `funded[person][bucket][month]` | assignments |
| `paid[person]` | entry `paid_by` |
| `borne[person][bucket]` | entry `shares` |

- **Position in a bucket**, per person: `Σ funded − Σ borne`, folded from the budget start so
  it carries over. Negative means that person is consuming more of this category than they
  have put in. `BucketState.funders[]` carries one of these per person; the bucket's own
  `assigned`, `activity` and `available` are the household's totals.
- **Debt**, per person: `Σ borne − Σ paid`. Unchanged.

`shares` is produced from the bucket's split **when the entry is created, and then stored**.
It is an audit trail, not an instruction — the same treatment `rule` already gets. Reading the
split live would mean that editing a bucket silently rewrites who owed whom across months of
history.

Precedence when an entry is created, most specific first: line-level splits on a receipt, an
explicit split on the entry, the split of the bucket it lands in, and finally the payer alone
when there is no bucket to ask.

## Worked example

Funding deliberately disagrees with the split, because that is the whole point.

| bucket | funded (me / partner) | split |
|---|---|---|
| rent | 2000 / 1200 | 50 / 50 |
| food | 1500 / 1500 | 50 / 50 |
| games | 300 / 0 | 100 / 0 |

**I pay rent, 3200.** Split says 1600 each.

| | rent position | debt |
|---|---|---|
| me | 2000 − 1600 = **+400** | paid 3200, bore 1600 → owed **1600** |
| partner | 1200 − 1600 = **−400** | owes me **1600** |

Partner's rent is red: they agreed to half of it and funded 1200 of a 3200 bill. The split did
not bend to the funding.

**Partner pays food, 2000.** Split says 1000 each. Food position: +500 each. Running debt:
partner owes me **600**.

**Partner buys games, 100.** Split is 100/0, so **I** bear all of it. Games position: me +200.
Partner paid 100 and bore nothing, so running debt: partner owes me **500**.

That last one is the case that motivated this: a bucket only I fund, spent against by someone
else, recorded as money I owe them.

## Two signals, deliberately not merged

They are fixed in different ways and can point in opposite directions at the same time.

| | means | fix by |
|---|---|---|
| **bucket red for a person** | your plan does not cover what you consume in this category | funding more, spending less, or changing the split |
| **debt** | cash has not moved to match what you bear | paying each other |

After the rent payment above I am owed 1600 *and* my partner's rent envelope is 400 short.
Both are true and neither implies the other.

## Filling to target

A target belongs to the household, so filling one shares the **shortfall** in the bucket's
split ratio — four people at 25% each cover a quarter. Only the shortfall, not the target:
somebody who has already funded their part is not asked again because somebody else has not.
That does mean an over-funder subsidises the split of what remains, which is the same thing as
having agreed to cover a quarter of the category.

Every funder's file is written in one commit (`assign_across`). Separately would have been a
fetch, commit and push each — four people over eight buckets is thirty-two round trips — and
a repo that briefly holds one person's contribution and not the others' shows an envelope
nobody chose to leave that way.

The other two strategies stay personal: what *you* assigned or spent last month says nothing
about what anyone else did.

Nobody's funding is ever reduced, and any funder's ready-to-assign may go negative. Refusing
would leave the plan half-applied, which is harder to reason about than an overcommitment you
can see.

## Colour, and what it can no longer mean

Bars are per funder and coloured by person, so **colour names identity, not state**. Envelope
state moved to the figure beside the bar and the row's severity edge, and an overspent
funder's bar carries a hatch — which reads without depending on hue at all.

Eight colours, assigned by position in the member list rather than by hashing a person id: a
hash collides often enough in a four-person budget to make a stacked bar unreadable. Removing
a member re-colours everyone after them, which is rare and happens at a moment when the
colours are being re-learned anyway.

They avoid the four semantic hues (negative 25, warning 75, positive 155, brand 220) by a
comfortable margin, because a member whose colour is the same green as "healthy" reads as a
judgement rather than a name.

🔴 They are declared in **plain CSS, not `@theme`**. Tailwind only emits a `@theme` variable
that some generated utility references, and these are used through inline `var()` on a bar
whose width is computed — so it stripped all eight and every bar rendered transparent.

## The editable figure is yours

The row shows the household's activity and available, but the **editable column is the acting
person's own funding** and is labelled that way. It briefly showed the household total in an
editable field, which meant pressing Enter replaced *your* funding with everybody's combined
figure — the field you can type into must be the figure you own.

The row's "fill to target" goes through the same split-ratio fill as the bulk button, scoped
to one bucket. Writing the target into the assign field instead would set one person's
funding to the whole household target.

## Two shapes for two questions

The bars toggle, because they answer different things:

- **Separate** — one bar per funder, each measured against *their own* contribution. "Is each
  of us within our own share?" It is the only shape where one person being over while everyone
  else is under is visible at a glance.
- **Stacked** — one bar, segments sized by what each person spent against the household total.
  "How much of this envelope is gone, and who spent it?"

The choice is a view preference in localStorage: it belongs to a browser, not to the
household.

## Acting as somebody else

A pill in the header names who this browser speaks for, because in a budget where several
people's figures sit side by side, "whose ready-to-assign is this" needs an answer on screen
rather than inferred.

It also switches, which is a testing affordance — driving the app as several placeholder
members shows how a shared budget behaves without needing four GitHub accounts. The rule that
makes it safe rather than an impersonation hole is a single one:

> Only a member with **no GitHub login** can be acted as.

A placeholder is a stand-in nobody can sign in as, so speaking for one speaks for a stand-in
rather than for somebody real. A member with a login always speaks for themselves and no
header changes that. Without it, anyone with repo access could attribute their spending to
their partner — precisely what the ledger exists to record honestly.

The server enforces this independently of the UI, and the **commit author stays the signed-in
person**, so `git log` still records who actually pressed the button.
