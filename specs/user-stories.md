# User Stories

What the interface is optimised for. Each story names the path and the cost in taps, because
"functional" is not the same as "usable at a checkout with one hand".

These are the yardstick for UI changes: a change that makes any of these longer needs a reason.

## 1. Log a shared expense while standing at the till

*I just paid for groceries. Both of us share it. I have one hand and ten seconds.*

**`+` → amount, payee → Save.** Three taps and two fields, from wherever you already were.

- The add button is global, not part of the entries screen. Logging an expense should never
  depend on being on the right tab first, so it is a floating action fixed at the inline end,
  clear of the mobile tab bar, and it opens a dialog rather than an inline form.
- The amount field takes focus on open, so typing starts immediately.
- `n` opens it from the keyboard, but never while a field is focused — otherwise it would
  fire in the middle of typing a payee.
- The amount field takes a magnitude. The kind decides the sign, because typing a leading
  minus for every purchase is a paper cut and forgetting it is silent.
- The split comes from the rules. Nothing about who owes whom has to be entered.
- Date defaults to today. Bucket is optional — an uncategorised entry is better than an
  abandoned one.

`Split` previews what the rules will do before saving, for the cases where that matters.

## 2. Can we afford to eat out tonight?

*One number, immediately.*

**Month tab.** The envelope list is grouped, and every row shows `available` with a progress
bar. Red means overspent, amber means nearly gone. No tap required — the answer is on screen
when the tab opens.

## 3. Payday: put the money into envelopes

*Income landed. Fill the envelopes without arithmetic.*

**Month tab → type into the assigned field, or `Fill to target`.**

- `Ready to assign` is the hero: it is the number that governs every other decision here.
- Each bucket with a monthly target and a shortfall offers a one-tap fill.
- Assigned amounts are edited in place. Enter commits, Escape reverts, the field selects on
  focus so typing replaces rather than appends.

## 4. Who owes whom, and settle it

*End of month. Square up.*

**Balances tab.** It states the answer in words — "You are owed" — above any table, then the
suggested transfers. The `Settle` button appears **only** on the row where the signed-in
person is the one who owes: the API records whatever it is asked to, so a button on the other
row would make it one tap to move a balance the wrong way.

## 5. Where did the grocery money go?

*The envelope is empty and it is the 20th.*

**Entries tab → bucket filter.** The header shows the filtered total. Tapping a row expands
it to show each person's share, which bucket it hit, who paid, and which rule produced the
split. Delete lives inside that expanded panel, not on the row, so it cannot be hit by
accident while scrolling.

## 6. Add a partner to the budget

*Two people, one household.*

**Settings → People**, plus adding them as a collaborator on the data repo.

Two steps, because they are two different things and the screen says so: membership decides
who can hold a share of an entry, GitHub repo access decides who can sign in at all. Removing
a member is refused while any entry still references them.

## Deliberately not optimised

- **Bulk entry.** Importing a bank statement is a different job from logging one expense, and
  building it into this form would slow the common case down.
- **Reporting.** There are no charts. The month view answers "how am I doing", and anything
  beyond that is a question for `git log` or the API.
