# Funding And Split

> Status: **proposed**. Nothing below is built yet.

How much you put into a bucket and how much of its spending you bear are two different
decisions. Today the app conflates them: buckets are per-person lists, and the split comes
from a rules file keyed by payee. This separates them.

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

Funding stays exactly where it is. Only the bucket definition moves and gains `split`.

Rules stop being about people, which is the simplification that falls out of this. A rule
carries `split` and a per-person `bucket` map today; with one shared bucket that owns its own
split, a rule is pure categorisation:

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
  have put in.
- **Debt**, per person: `Σ borne − Σ paid`. Negative means they have handed over more cash
  than they bear, so the household owes them. This is unchanged.

`shares` is produced from the bucket's split **when the entry is created, and then stored**.
It is an audit trail, not an instruction — the same treatment `rule` already gets. Reading the
split live would mean that editing a bucket silently rewrites who owed whom across months of
history.

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
not bend to the funding — that is the behaviour being asked for.

**Partner pays food, 2000.** Split says 1000 each. Food position: +500 each. Running debt:
partner owes me **600**.

**Partner buys games, 100.** Split is 100/0, so **I** bear all of it. Games position: me +200,
partner unchanged at 0. Partner paid 100 and bore nothing, so running debt: partner owes me
**500**.

That last one is the case that motivated this: a bucket only I fund, spent against by someone
else, recorded as money I owe them.

## Two signals, deliberately not merged

The screen has to keep these apart, because they are fixed in different ways and can point in
opposite directions at the same time.

| | means | fix by |
|---|---|---|
| **bucket red for a person** | your plan does not cover what you consume in this category | funding more, spending less, or changing the split |
| **debt** | cash has not moved to match what you bear | paying each other |

You can be owed money while your own side of a bucket is red. In the example above, after the
rent payment I am owed 1600 *and* my partner's rent envelope is 400 short. Both are true and
neither implies the other.

## Rules

1. `split` sums to 1 across the budget's members. Validated on write.
2. A new bucket defaults to an equal split among current members.
3. Adding a member does not change existing splits; they bear 0 until a split is edited.
4. An entry may override the split — a gift from `gifts` that is entirely mine. The bucket
   split is a **default**, not a law.
5. Overspending needs no special case. The split decides who bears it, and that person's
   position goes negative. Exactly like YNAB, only per person.
6. Income, transfers and settlements carry no bucket and therefore no split.

## Pros

- Matches how the decision is actually made. Choosing how much cash to put in this month is
  not the same as choosing what is fair, and the current model forces them to be.
- The motivating cases need no special rule: "a bucket only I fund" is just `split: {me: 1}`.
- Rules stop mentioning people at all, and lose their per-person bucket map.
- The split is visible on the category, which is where someone would look for it, rather than
  in a payee-matching list read top to bottom.
- The ledger is untouched. Debt still derives from paid versus borne.
- Much of it already exists: assignments are already per person, and `available` already
  filters shares by person, so per-person positions are not new machinery.

## Cons

- 🔴 The split must stay frozen onto the entry. Entries already store `shares`, so this is a
  property to preserve rather than build — but if anything ever recomputes shares from the
  bucket on read, editing a split silently rewrites history.
- Two numbers per person per bucket makes the month screen denser. It likely needs a
  mine/household toggle rather than four figures on every row.
- Splits need maintaining as membership changes, and a stale split is silent.
- Funding a bucket you hold a 0% split in is legal and almost always a mistake. Worth a
  warning, not a refusal.
- "Owed money while my bucket is red" is correct and initially confusing. It is a wording
  problem on the month screen, not a modelling one.
- 🔴 Breaking schema change: buckets move to the repo root and gain `split`, rules lose theirs.
  There is no migration path planned — the data would be rewritten in place.

## Open questions

- **Default split for a new bucket** — equal among members, with a one-tap "make this mine"?
- **A `payer` split mode**, where whoever pays bears it entirely and no debt ever arises. Names
  a real case (shared category, personal spending) but is a second concept; not proposed yet.
- **Covering someone's deficit.** If a partner's side of a bucket is −400, is there an action
  that moves funding from one person to another, or do they simply fund more next month?
- **What the month screen leads with** — my position, or the household's.
