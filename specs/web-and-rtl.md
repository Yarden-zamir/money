# Web App And RTL

React 19 + Vite + TypeScript, TanStack Query for server state, Tailwind 4 for styling, and a
generated TypeScript client. There is no hand-written `fetch` call against the API anywhere in
the app — every request goes through the generated client, so a backend change that breaks a
call site fails `tsc`.

## Hebrew And RTL Are Not A Theme

Hebrew is a first-class language, not a translation applied to a layout designed for English.
The rules that keep it working:

- **Logical CSS properties only.** `ms-4`/`me-4`, `ps-2`/`pe-2`, `start-0`/`end-0`. The
  physical equivalents are banned in app code and `tests/test_rtl.py` fails the build on
  them, because they are the single most common way an RTL layout silently breaks. The same
  suite checks that the two locale files define identical keys, and that the bidi isolates in
  `formatMoney` are still there — they are invisible characters a cleanup could easily drop.
- `dir` is set on `<html>` from the active language, and the whole tree inherits it. No
  component sets `dir` on itself.
- **Amounts are isolated, not forced LTR.** `formatMoney` wraps its output in a FIRST STRONG
  ISOLATE (U+2068), never a LEFT-TO-RIGHT ISOLATE. `Intl` already emits the marks each locale
  needs — `he-IL` wraps the amount in RLM and puts ₪ after it — and forcing LTR fought those
  marks, which is why the shekel sign landed on a different side depending on the sign of the
  number. FSI isolates the run from its surroundings and lets its content pick direction.
- **A sequence of amounts needs its own isolate.** Isolating each amount individually is not
  enough: `spent / target` still flips as a *sequence* in Hebrew, so the target appeared
  first. Anything read as a fraction or range goes in one `dir="ltr"` run.
- Formatting goes through `Intl.NumberFormat` and `Intl.DateTimeFormat` with the active
  locale. No manual string concatenation of currency symbols.
- Icons that encode direction (back, forward, trend arrows) flip via the `.icon-directional`
  class, which uses the `:dir(rtl)` selector; icons that do not (a plus, a wallet) never flip.
  Characters that are already **Bidi-Mirrored**, such as `‹` and `›`, must *not* get that
  class: the text engine flips them, and flipping again would point them the wrong way.

Translations live in `src/locales/{he,en}/*.json`. `en` is the source of truth for keys, and a
missing key falls back to English rather than rendering a raw key.

## Dependency Pins

Two pins exist for reasons that are not obvious from `package.json`:

Everything is on its latest release except one, which is held back deliberately:

- **TypeScript 5.9.3**, not 7.x, enforced by an override in `pnpm-workspace.yaml` so
  `pnpm update --latest` cannot reintroduce it. `@hey-api/openapi-ts` drives the TypeScript
  compiler API, and TypeScript 7's native port does not expose it — `ts.SyntaxKind` is
  undefined and client generation fails outright. Drop the override once the generator
  supports 7.x.

`pnpm-workspace.yaml` also carries `minimumReleaseAgeExclude`, pnpm's supply-chain check for
packages published very recently. The Dockerfile copies that file into the build stage:
without it the image installs under different rules than a developer does, and fails on
packages that pass locally.

## Looking At It

`node tools/shoot.mjs [dir]` renders every screen at desktop and phone width, in both
languages, against stubbed API responses. Running the real backend would need GitHub auth and
a live data repo, neither of which says anything about layout.

Every RTL bug fixed so far was invisible in code review and obvious in a screenshot: bucket
names colliding with their group, a currency symbol switching sides, a fraction reading
backwards, the header overflowing a phone. Take a screenshot before claiming an RTL fix.

## Mobile

Phones get a bottom tab bar; the top bar's inline nav is hidden below `sm`. The previous
single top bar overflowed at 390px and clipped both the tabs and the language picker.

Adding an expense is a floating action fixed above the tab bar, because that is what people
open the app to do. Destructive actions are never on a row — delete lives inside a row's
expanded panel, so it cannot be hit while scrolling.

Controls are at least 44px tall (`.control`, `Button`).

## Visual Language

The subject is a household ledger, not a fintech dashboard, and the palette says so.

- **Accent is a desaturated petrol**, replacing a generic indigo. It reads as ink, and it sits
  far enough from the semantic greens and reds that it never competes with them. Neutrals
  carry the same blue-green bias so they read as chosen rather than as inherited grey.
- **Semantic colour is reserved for money and envelope state** — an amount, a progress bar, a
  status chip — and is never used as chrome. That is what keeps it unambiguous.
- **The accent inverts between themes**, so text on it must invert too: `text-on-brand`, never
  `text-white`. A light accent with white text fails contrast in dark mode.
- **Arithmetic is set in monospace.** A ledger's columns line up; IBM Plex Mono with tabular
  figures makes a column of amounts scannable, and pairs with Heebo, which carries the Hebrew.
- **One signal per state.** A bucket's bar encodes proportion spent by *length*; its colour
  only distinguishes states that need attention — overspent, nearly empty, or emptied exactly
  on plan, which is a paid bill and neither a warning nor a success.

## Icons

SVG on a 24-unit square viewBox, never text glyphs. A glyph sits on a text baseline rather
than in the middle of its box, so it can only ever be nudged into approximate alignment and
the approximation shifts with the font — the action button's plus was a `+` with a negative
margin. `currentColor` throughout, so an icon inherits the colour of what it sits in.

Only icons that encode reading direction take `directional`. A plus, a gear or a wallet
never mirrors.

Native `<select>` draws its own arrow flush against the edge and ignores padding, so `Select`
suppresses it and draws one positioned with a logical inset. Width is forced only when the
caller asks: an auto-width select inside a shrink-to-fit wrapper resolves `w-full` against
nothing, dropping the space reserved for the arrow and putting the chevron on the label.

## Motion

One animated figure per screen, and only headline ones — the ready-to-assign total counts up
on load. A column of numbers all animating at once is noise, and a figure still in motion
cannot be compared with the one beside it. `useCountUp` returns the target immediately when
the viewer prefers reduced motion.

## Keyboard

Declared in one place (`features/Shortcuts.tsx`) so every shortcut is discoverable, with `?`
opening the list — a shortcut nobody can find is a shortcut nobody uses.

Bare letters never fire while a field is focused. This app is mostly typing, and a letter
that triggers an action mid-word is worse than no shortcut. Combinations with the command key
still work while typing, because those cannot happen by accident.

## Freshness and instant feedback

Queries poll every 10 seconds, but only while the tab is visible — polling a backgrounded tab
spends the other person's rate limit for a screen nobody is looking at. Polling is affordable
because the server caches every read against the commit sha, so an unchanged budget is a
Redis hit rather than a walk of the ledger.

Writes go to git — a commit, a rebase, a push — which is fast but never instant. Assigning
and reordering patch the cache first so the number moves on keypress and the row lands where
it was dropped. Correctness comes from the rollback: the previous snapshot is restored on
failure and the query is invalidated on settle, so **an optimistic value is never allowed to
become the truth**.

`cancelQueries` runs before each patch, so an in-flight refetch cannot land afterwards and
revert what was just shown.

## Reordering

Buckets carry an `order`, written per bucket rather than as a list, so two people reordering
different groups at once do not overwrite each other — each writes only what it moved.

A row is draggable only while its handle is held. A permanently draggable row containing an
input cannot be clicked into or selected in — the browser starts a drag instead — which is
why the first attempt at this did not work at all.

`dataTransfer` is always set: Firefox refuses to start a drag without a payload, and without
an explicit `effectAllowed` the cursor never shows a move affordance.

Dropping onto a row adopts that row's group as well as its position, so dragging between
groups needs no separate gesture. Dropping onto a group header appends to it.

Dragging is a pointer gesture, so every draggable row also carries up/down buttons. They are
hover-revealed on a mouse and **always visible on touch**, where hover does not exist and
HTML5 drag does not work — there, they are the only way to reorder.

## Controls

Conventions that exist because they drifted once already:

- **Action order is not a per-screen decision.** `FormActions` places the primary action at
  the inline start, secondary next, and anything destructive pushed to the inline end. Screens
  used to arrange their own buttons and disagreed, so the blue button landed on a different
  side depending where you were.
- **Every field has a visible label.** Placeholders are not labels: they disappear the moment
  a field is filled, which left the member editor as three anonymous boxes once it had data.
  Placeholders carry examples, not names.
- **Width is opt-in.** `Input`/`Select` are full width unless given `fullWidth={false}`; a
  fixed width without it fights the base utility and the winner depends on stylesheet order.
  `tests/test_rtl.py` fails the build on that combination.
- **Lists whose order is meaningful say so.** Rules are numbered and moved with explicit
  controls, because "first match wins" is invisible otherwise.
- **Destructive actions are separated and coloured**, never adjacent to a routine one, and
  never on a scrollable row where a thumb lands.

## Structure

```
web/src/
  api/            generated client, regenerated by `pnpm run generate:api`; never edited
  features/       one folder per screen: budget, entries, buckets, balances, settings
  components/     shared presentational pieces
  lib/            formatting, i18n setup, direction handling
  locales/        he/, en/
```

Money is a `Decimal`-safe string end to end. The frontend never parses an amount into a JS
number for arithmetic; it formats for display and sends strings back. Totals are computed by
the API, which has a real decimal type.

## Screens

- **Month** — a ledger, not a list of cards. One set of column headers rather than a label
  repeated on every row; groups carry a subtotal, because "can this category cover the rest
  of the month" is a question about the group; and a severity edge marks overspent rows only.
  The summary strip states income, assigned, ready-to-assign and how many envelopes are
  overspent — a single hero number answered none of the last three.
- **Entries** — ledger with filters, inline split editor showing both dimensions (buckets and
  people) at once, and a link to the commit that recorded each change.
- **Balances** — net position per person and the suggested settle-up, with a one-tap
  settlement. The Splitwise half.
- **Rules** — edit default splits, with a live preview against a sample entry so the effect is
  visible before saving.
- **Settings** — budgets, API keys, language.

## Auth In The Browser

Session cookie, `HttpOnly` + `Secure` + `SameSite=Lax`. The SPA never holds a token in
JavaScript, so an XSS bug cannot exfiltrate a long-lived credential. A 401 sends the user to
the GitHub OAuth start endpoint.

The API key management screen shows a key exactly once, at creation, with a copy button and a
plain warning that it will not be shown again.
