# User Stories

What the interface is optimised for. Each story names the path and the cost in taps, because
"functional" is not the same as "usable at a checkout with one hand".

These are the yardstick for UI changes: a change that makes any of these longer needs a reason.

## 0. Start using it at all

*I signed in. I have never used this and I do not have a "budget repo".*

**Name it → Create budget.** One field, then a working budget with buckets in it.

- Creating is the offer, not connecting. Asking a first-time user for the repo that holds
  their budget data described a thing they did not have, and left the only route in as
  hand-writing YAML on github.com. Connecting is still there, one link away, for the people
  who genuinely do have one.
- The repo name, the slug and your person id are all derived and hidden behind *Advanced*.
  None of them is a decision worth having an opinion about on a first screen.
- A line under the form names the repo that is about to be created. Creating a repo on
  someone's GitHub account is a visible external side effect and should not be a surprise.
- You land on a month screen with buckets already in it, so the first expense has somewhere
  to go.

*Someone shared their budget with me and forgot to add me.*

**Join budget.** One field, pre-filled with a free id.

- Detected by `me` being null while `can_write` is true. Before this, every screen answered
  403 telling you to edit `budget.yaml` — including the member editor that would have fixed
  it.
- A read-only viewer is told to ask a member instead, rather than shown a form that would
  fail. They cannot fix it themselves and pretending otherwise wastes their time.

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
- Date defaults to today.
- Bucket is optional *while a rule can supply one* — an uncategorised entry is better than an
  abandoned one. With no rules defined, an expense with no bucket cannot be saved at all, so
  the blank option becomes "Choose a bucket" rather than a choice that silently fails. With no
  buckets at all the form says so before anything else, because every other field is then
  wasted typing.

`Split` previews what the rules will do before saving, for the cases where that matters.

## 2. Can we afford to eat out tonight?

*One number, immediately.*

**Month tab.** The envelope list is grouped, and every row shows `available` with a progress
bar. Red means overspent, amber means nearly gone. No tap required — the answer is on screen
when the tab opens.

## 3. Payday: put the money into envelopes

*Income landed. Fill the envelopes without arithmetic.*

**Month tab → `Fund all targets`,** or type into the assigned field for one bucket.

Three bulk strategies, because funding envelopes one at a time is the most repeated chore in
envelope budgeting: top every bucket up to its target, repeat last month's assignment, or
match what was actually spent last month. Topping up never reduces an assignment — someone
who deliberately over-assigned should not have it silently clawed back.

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

## 4b. Cover an overspend

*Eating out is red and it is the 20th.*

**Month tab → `Move money`.** One action moves from one envelope to another and refuses to
move more than the source holds. Editing two assignment figures instead means doing the
arithmetic yourself and leaving the budget briefly wrong between the two saves.

That is **one commit**, not two. It used to write each side separately, which meant the repo
briefly held money taken from one envelope and not yet in the other — the exact state this
story exists to avoid, made observable to anyone reading the history.

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

## 7. The rent is due again

*The same four charges every month. I do not want to retype them, and I do not want them
appearing behind my back.*

**Scheduled tab → Post.** Due charges are listed with an `overdue` chip; each becomes a real
entry on one tap.

The app never posts on its own. A recurrence produces dates that are *due*; a person confirms
each one, so every commit still has an author. Templates collapse to a summary row — most
visits here are to check what is coming, not to edit.

## Deliberately not optimised

- **Bulk entry.** Importing a bank statement is a different job from logging one expense, and
  building it into this form would slow the common case down.
- **Reporting.** There are no charts. The month view answers "how am I doing", and anything
  beyond that is a question for `git log` or the API.
