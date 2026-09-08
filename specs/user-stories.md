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
- The split comes from the bucket's default and is on screen. Nothing about who owes whom
  has to be typed.
- Date defaults to today.
- Bucket is required for an expense, and usually already filled: the payee autocomplete and
  the suggestion engine carry the bucket this payee went to last time. With no buckets at all
  the form says so before anything else, because every other field is then wasted typing.

The split panel is **always on the form**, pre-filled from the bucket's default, so what
will be recorded is on screen before the save rather than applied out of sight. The common
case still costs nothing: the default is already selected.

## 1b. It was not an even split

*I paid for dinner; she had the wine.* — **Adjust → +60 for Dana → Save.**

*I ate alone.* — **Just me → Save.** One tap. This is the case that made the panel
permanent: with the default applied silently, a solo meal in a shared food bucket came out
split in half and nothing on screen said so.

*One receipt, and the wine was hers.* — **Receipt lines → By item → untick me on the wine
→ Save.** Each line is shared equally by whoever is ticked on it, and the entry's shares are
the per-person sums. The lines are sent with their own splits, so the ledger records which
line was whose.

Seven modes, then: just me, equally (tick who is in), percent, shares (relative weights),
exact amounts, adjust (a fixed extra for someone, the rest equal), and by item when there
are receipt lines. The amounts are derived and shown live; the remainder is allocated the
way the backend does it, largest share takes the rounding, so what is shown is what is saved
and it never fails validation. Splitwise offers the same modes; here they cost no extra
screen.

Who paid is one select, with *several people paid* a link away.

The bucket's default split — the thing the panel opens with — is edited with the **same
panel** on the bucket's options, minus the money-shaped modes: just me, equally, percent or
shares, shown as the percentage each works out to. A default and an entry's split are the
same decision at two different times, and should not need two vocabularies.

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
suggested transfers. `Settle` appears on every transfer the signed-in person is a side of,
from either side, because the person who is owed is usually the one holding the phone when
the money arrives — and if their partner does not use the app nobody else could record it.
The button confirms in words which way the payment goes, and names the payer explicitly in
the request, so recording it from the receiving side cannot book it backwards.

## 4b. Cover an overspend

*Eating out is red and it is the 20th.*

**Month tab → `Move money`.** One action moves from one envelope to another and refuses to
move more than the source holds. The action strip wraps rather than scrolling sideways, so
this button is on screen at phone width instead of past its edge. Editing two assignment figures instead means doing the
arithmetic yourself and leaving the budget briefly wrong between the two saves.

That is **one commit**, not two. It used to write each side separately, which meant the repo
briefly held money taken from one envelope and not yet in the other — the exact state this
story exists to avoid, made observable to anyone reading the history.

## 5. Where did the grocery money go?

*The envelope is empty and it is the 20th.*

**Entries tab → bucket filter.** The header shows the filtered total. Tapping a row expands
it to show each person's share, which bucket it hit, and who paid. Delete lives inside that expanded panel, not on the row, so it cannot be hit by
accident while scrolling.

## 5a. We were abroad

*Forty dollars for a taxi. I do not know yet what the card will charge.*

**`+` → amount, payee → Currency: USD → Save.** One extra select. The default converts at the
day's rate and says what will be recorded: *−$42.00 → −₪155.82*. The two alternatives are in
the same select: type the rate from the card statement, or *keep in USD for now*.

Kept dollars stay dollars. The Transport row shows *−$42.00 unconverted* as a chip under its
shekel figure, the balances screen shows the dollar debt as its own line with its own
`Settle`, and nothing is ever added across the two. When the statement arrives, the chip
opens *Convert the USD in Transport*: one rate, one commit, every dollar entry in the bucket
at once. One entry at a time is the same panel inside the entry's detail.

## 5b. Which entry was that?

*Some shop, some time this spring, I think Dana mentioned wine.*

**Entries tab → type in the search box.** Every word has to match somewhere on the entry —
payee, note, tags, place, receipt lines — and typing widens the month to *all*, because
someone searching is looking for what they cannot place. Person and kind filters sit beside
the month and bucket ones. Rows show a comment or paperclip count, so a conversation or a
receipt is findable from the list rather than by opening every row.

## 5c. Ask about an entry

*"Did you keep the receipt?" — without leaving the ledger.*

**Entries tab → row → Comments → type → Enter.** A chat under the entry: your messages at the
inline end, everyone else's at the start with their colour, timestamps in the reader's
locale. The thread polls every few seconds while it is open, so a reply arrives without a
refresh, and your own message shows at once. Only its author can delete a message.

## 5d. Keep the receipt

*I will not remember what this 284 was.*

**`+` → Add a photo → camera → Save**, or on an existing entry, **row → Add a photo.** The
photo is committed beside the entry and shows as a thumbnail that opens full size. A photo
chosen on the add form is uploaded right after the save, because an attachment hangs off an
entry id and there is none until the commit lands. Nothing is read out of the photo yet.

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
