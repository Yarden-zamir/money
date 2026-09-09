"""Reading and writing budget state as files in a git repo.

Every mutation is one commit. There is no batching, because a change that does not appear in
`git log` is a change the user cannot audit.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from money.domain.amounts import ZERO
from money.domain.models import Bucket, Budget, Comment, Entry, Fx, Member, Scheduled, Target
from money.store import yamlio
from money.store.gitrepo import Commit, GitRepo, PushRejected, write_lock

SCHEMA_VERSION = 2

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id() -> str:
    """A ULID: time-ordered, so ledger files stay in creation order without a counter."""
    timestamp = int(time.time() * 1000)
    payload = int.from_bytes(os.urandom(10), "big")
    value = (timestamp << 80) | payload
    return "".join(CROCKFORD[(value >> shift) & 0x1F] for shift in range(125, -1, -5))


@dataclass(frozen=True)
class Actor:
    """Who is making a change, and the token that proves they may."""

    login: str
    name: str
    email: str
    token: str


class DataError(RuntimeError):
    """A file in the data repo is missing or does not parse."""


def ledger_path(month: str) -> str:
    return f"ledger/{month}.yaml"


# Buckets are shared: one definition the whole household funds and spends against, rather
# than a list per person that happened to use matching ids.
BUCKETS_PATH = "buckets.yaml"


def assignments_path(person: str, month: str) -> str:
    return f"people/{person}/assignments/{month}.yaml"


SCHEDULED_PATH = "scheduled.yaml"

# Daily exchange rates the app fetched, keyed by day then currency: budget units per one
# unit of the foreign currency. Committed so a repo is reproducible offline and two people
# converting on the same day get the same rate. A rate a person typed never goes here — the
# table is what the provider said, not what somebody chose.
RATES_PATH = "rates.yaml"

RateRow = tuple[date, str, Decimal]


def _bucket_sort_key(bucket: Bucket) -> tuple[str, int, str]:
    """Group, then the arranged position, then name as a stable tiebreak.

    Name rather than id, because two buckets created together both start at order 0 and the
    list should read alphabetically until someone actually arranges it.
    """
    return (bucket.group or "", bucket.order, bucket.name)


def _describe_target(target: Target | None) -> str:
    if target is None or target.kind == "none":
        return "no target"
    if target.kind == "monthly":
        return f"{target.amount:.2f}/month"
    return f"{target.amount:.2f} by {target.due}"


def describe_bucket_change(before: Bucket | None, after: Bucket) -> str:
    """What actually changed about a bucket, for the commit subject.

    `put_bucket` replaces the whole bucket, so the write itself does not say whether this was
    a rename, a re-target or a drag. "bucket: yarden fun-money" was the same line for all of
    them, which made the history unreadable exactly when someone was trying to find what
    broke. Comparing against the previous version is the only place that information exists.

    Several things can change at once — renaming while dragging into another group — so this
    lists all of them rather than picking one and quietly dropping the rest.
    """
    if before is None:
        return f"create {after.name}"

    changes: list[str] = []
    if before.name != after.name:
        changes.append(f"rename {before.name} → {after.name}")
    if before.group != after.group:
        changes.append(f"move {after.name} to {after.group or 'no group'}")
    if before.target != after.target:
        changes.append(f"target {after.name} {_describe_target(after.target)}")
    if before.archived != after.archived:
        changes.append(f"{'archive' if after.archived else 'restore'} {after.name}")
    if not changes and before.order != after.order:
        changes.append(f"reorder {after.name}")

    return ", ".join(changes) or f"update {after.name}"


def _describe_names(names: list[str], limit: int = 3) -> str:
    """A few names, then a count. Subjects are one line, and the diff shows the rest."""
    shown = names[:limit]
    rest = len(names) - len(shown)
    return ", ".join(shown) + (f" and {rest} more" if rest else "")


def _describe_assignment(
    amounts: dict[str, Decimal],
    before: dict[str, Decimal],
    names: dict[str, str],
) -> str:
    """A subject line for one or many envelopes changing at once.

    One bucket keeps the precise form, because that is the common case and the figure it moved
    from is the useful part. Several would run past any sensible subject length, so they are
    named and counted — the diff is one line per bucket and the history view shows it.
    """
    changed = [b for b, amount in amounts.items() if amount != before.get(b, ZERO)]
    if not changed:
        return "no change"

    if len(changed) == 1:
        bucket = changed[0]
        return f"{names.get(bucket, bucket)} {before.get(bucket, ZERO):.2f} → {amounts[bucket]:.2f}"

    return _describe_names([names.get(bucket, bucket) for bucket in changed])


def describe_list_change(before: list[str], after: list[str], noun: str) -> str:
    """Added and removed names for any list written wholesale (members, recurrences).

    All three are replaced as a unit, so without a diff the subject can only report a count —
    "rules: update defaults" was literally the same string every time.
    """
    added = [name for name in after if name not in before]
    removed = [name for name in before if name not in after]

    parts = []
    if added:
        parts.append(f"added {', '.join(added)}")
    if removed:
        parts.append(f"removed {', '.join(removed)}")
    if not parts:
        parts.append("reordered" if before != after else "edited")

    return f"{len(after)} {noun}{'' if len(after) == 1 else 's'} ({'; '.join(parts)})"


def note_path(entry_id: str) -> str:
    return f"notes/{entry_id}.md"


def comments_path(entry_id: str) -> str:
    return f"comments/{entry_id}.yaml"


def attachments_prefix(entry_id: str) -> str:
    return f"attachments/{entry_id}/"


@dataclass(frozen=True)
class Attachment:
    """A file kept beside an entry: a receipt photo, a PDF invoice.

    Stored in the data repo rather than in a blob store, for the same reason everything else
    is: the repo is the budget, and a receipt that only exists on a server this app runs on
    is a receipt you lose when the app goes. The cost is repo size — see specs/data-model.md
    for the limit that keeps it sane.
    """

    name: str
    size: int
    content_type: str


# What a receipt can be. Anything else is refused: the repo is shared by everyone in the
# budget, and "attach a file" must not become "put an executable in a repo people clone".
ATTACHMENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}

# Enough for a phone photo of a receipt, small enough that a year of them does not make the
# clone slow. Revisit if photos are ever resized client-side, which would allow a lower cap.
ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024


def _content_type_of(name: str) -> str:
    for content_type, extension in ATTACHMENT_TYPES.items():
        if name.endswith(extension):
            return content_type
    return "application/octet-stream"


class BudgetStore:
    def __init__(self, repo: GitRepo, cache: Any | None = None) -> None:
        self.repo = repo
        # Optional so the store stays usable in tests and the CLI without a Redis running.
        self.cache = cache

    # ---- reads ----------------------------------------------------------------------

    def budget(self) -> Budget:
        raw = yamlio.load(self.repo.read("budget.yaml"))
        if raw is None:
            raise DataError("budget.yaml is missing; this repo is not initialized as a budget")
        return Budget.model_validate(raw)

    def buckets(self) -> list[Bucket]:
        """Every bucket in the budget, in display order.

        Sorted on read as well as on write, because the file can be edited by hand and a
        reordering typed into YAML should take effect without needing the app to rewrite it.
        """
        raw = yamlio.load(self.repo.read(BUCKETS_PATH)) or []
        return sorted((Bucket.model_validate(item) for item in raw), key=_bucket_sort_key)

    def entries_for_month(self, month: str) -> list[Entry]:
        raw = yamlio.load(self.repo.read(ledger_path(month)))
        if raw is None:
            return []  # a month with no spending simply has no file
        if not isinstance(raw, list):
            raise DataError(f"{ledger_path(month)} must contain a list of entries")
        return [Entry.model_validate(item) for item in raw]

    def all_entries(self) -> list[Entry]:
        """Every entry, in ledger order. Balances need the whole history to be correct.

        This is the expensive read in the whole app — every ledger file, parsed and validated
        — and it is what balances and carryover both need. Cached against the commit sha, so
        a write lands on a new sha and the next read simply misses rather than needing anyone
        to remember to clear a key.
        """
        if self.cache is None:
            return self._read_all_entries()

        from money.api.cache import entries_key

        key = entries_key(self.repo.remote, self.repo.branch, self.repo.head_sha())
        raw = self.cache.get_or_set(
            key, lambda: [entry.model_dump(mode="json") for entry in self._read_all_entries()]
        )
        return [Entry.model_validate(item) for item in raw]

    def _read_all_entries(self) -> list[Entry]:
        entries: list[Entry] = []
        for path in self.repo.list_files("ledger/"):
            month = path.removeprefix("ledger/").removesuffix(".yaml")
            entries.extend(self.entries_for_month(month))
        return entries

    def assignments(self, person: str) -> dict[str, dict[str, Decimal]]:
        """One person's funding, keyed by month then bucket."""
        result: dict[str, dict[str, Decimal]] = {}
        for path in self.repo.list_files(f"people/{person}/assignments/"):
            month = path.rsplit("/", 1)[-1].removesuffix(".yaml")
            result[month] = yamlio.load(self.repo.read(path)) or {}
        return result

    def all_assignments(self) -> dict[str, dict[str, dict[str, Decimal]]]:
        """Everyone's funding, keyed by person, then month, then bucket.

        A shared bucket's state depends on what every funder put in, so the month view needs
        all of it rather than one person's slice.
        """
        return {member.person: self.assignments(member.person) for member in self.budget().members}

    def find_entry(self, entry_id: str) -> tuple[Entry, str] | None:
        """Locate an entry and the month whose file holds it."""
        for path in self.repo.list_files("ledger/"):
            month = path.removeprefix("ledger/").removesuffix(".yaml")
            for entry in self.entries_for_month(month):
                if entry.id == entry_id:
                    return entry, month
        return None

    def scheduled(self) -> list[Scheduled]:
        raw = yamlio.load(self.repo.read(SCHEDULED_PATH)) or []
        return [Scheduled.model_validate(item) for item in raw]

    def note(self, entry_id: str) -> str | None:
        """The long-form note for an entry, if one was written.

        Markdown in its own file rather than a field on the entry: a paragraph of context
        belongs somewhere a diff can show line by line, and somewhere a person can read
        without picking it out of YAML.
        """
        return self.repo.read(note_path(entry_id))

    def rates(self) -> dict[date, dict[str, Decimal]]:
        raw = yamlio.load(self.repo.read(RATES_PATH)) or {}
        return {
            day if isinstance(day, date) else date.fromisoformat(str(day)): {
                code: Decimal(str(rate)) for code, rate in (quotes or {}).items()
            }
            for day, quotes in raw.items()
        }

    def rate(self, currency: str, day: date) -> Decimal | None:
        return self.rates().get(day, {}).get(currency)

    def comments(self, entry_id: str) -> list[Comment]:
        """The conversation under one entry, oldest first — the order it was said in."""
        raw = yamlio.load(self.repo.read(comments_path(entry_id))) or []
        return sorted((Comment.model_validate(item) for item in raw), key=lambda c: c.id)

    def attachments(self, entry_id: str) -> list[Attachment]:
        """The files kept beside one entry, in the order they were added (names are ULIDs)."""
        found: list[Attachment] = []
        for path in self.repo.list_files(attachments_prefix(entry_id)):
            name = path.rsplit("/", 1)[-1]
            data = self.repo.read_bytes(path)
            if data is None:
                continue
            found.append(Attachment(name=name, size=len(data), content_type=_content_type_of(name)))
        return found

    def attachment(self, entry_id: str, name: str) -> bytes | None:
        # The name is a path segment written by us, but it arrives back from a URL: refuse
        # anything that could climb out of the entry's own directory.
        if "/" in name or name in ("", ".", ".."):
            return None
        return self.repo.read_bytes(attachments_prefix(entry_id) + name)

    def extras(self, entry_ids: list[str]) -> dict[str, tuple[int, int]]:
        """(comment count, attachment count) per entry, for badges on a list.

        Two `ls-files` calls and a parse of only the comment files that exist, so the common
        case — a ledger where a handful of entries have a conversation — costs nothing
        proportional to the ledger.
        """
        wanted = set(entry_ids)
        comment_counts: dict[str, int] = {}
        for path in self.repo.list_files("comments/"):
            entry_id = path.removeprefix("comments/").removesuffix(".yaml")
            if entry_id in wanted:
                comment_counts[entry_id] = len(yamlio.load(self.repo.read(path)) or [])

        attachment_counts: dict[str, int] = {}
        for path in self.repo.list_files("attachments/"):
            entry_id = path.removeprefix("attachments/").split("/", 1)[0]
            if entry_id in wanted:
                attachment_counts[entry_id] = attachment_counts.get(entry_id, 0) + 1

        return {
            entry_id: (comment_counts.get(entry_id, 0), attachment_counts.get(entry_id, 0))
            for entry_id in entry_ids
            if entry_id in comment_counts or entry_id in attachment_counts
        }

    def schema_version(self) -> int:
        raw = self.repo.read(".money/schema-version")
        if raw is None:
            return SCHEMA_VERSION  # a repo predating the marker is treated as current
        try:
            return int(raw.strip())
        except ValueError as exc:
            raise DataError(f".money/schema-version is not a number: {raw!r}") from exc

    def check_schema(self) -> None:
        """Refuse to touch data written by a newer version of the app.

        Reading it might appear to work while silently dropping fields this version does not
        know about, and the first write would then delete them.
        """
        found = self.schema_version()
        if found > SCHEMA_VERSION:
            raise DataError(
                f"this budget uses schema version {found}, but this app understands "
                f"{SCHEMA_VERSION}. Upgrade the app before writing to it."
            )

    def history(self, entry_id: str, limit: int = 50) -> list[Commit]:
        """Commits that touched one entry, found by its `Entry-Id` trailer."""
        return self.repo.log(grep=f"Entry-Id: {entry_id}", limit=limit)

    # ---- writes ---------------------------------------------------------------------

    def add_entry(self, entry: Entry, actor: Actor, rate_row: RateRow | None = None) -> str:
        """Write one entry. A rate the conversion fetched lands in the same commit."""

        def mutate() -> list[str]:
            entries = self.entries_for_month(entry.month)
            if any(existing.id == entry.id for existing in entries):
                raise DataError(f"entry {entry.id} already exists")
            entries.append(entry)
            self._write_ledger(entry.month, entries)
            return [ledger_path(entry.month), *self._record_rate(rate_row)]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"entry: add {entry.payee} {abs(entry.amount):.2f} {entry.currency}",
            trailers={"Entry-Id": entry.id},
        )

    def replace_entry(self, entry: Entry, previous_month: str, actor: Actor) -> str:
        def mutate() -> list[str]:
            remaining = [e for e in self.entries_for_month(previous_month) if e.id != entry.id]
            if entry.month == previous_month:
                self._write_ledger(previous_month, [*remaining, entry])
                return [ledger_path(previous_month)]

            # An edited date can move an entry between monthly files, so both are touched.
            self._write_ledger(previous_month, remaining)
            self._write_ledger(entry.month, [*self.entries_for_month(entry.month), entry])
            return sorted({ledger_path(previous_month), ledger_path(entry.month)})

        return self._commit(
            mutate,
            actor=actor,
            subject=f"entry: update {entry.payee} {abs(entry.amount):.2f} {entry.currency}",
            trailers={"Entry-Id": entry.id},
        )

    def delete_entry(self, entry: Entry, month: str, actor: Actor) -> str:
        def mutate() -> list[str]:
            remaining = [e for e in self.entries_for_month(month) if e.id != entry.id]
            self._write_ledger(month, remaining)
            return [ledger_path(month)]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"entry: remove {entry.payee} {abs(entry.amount):.2f} {entry.currency}",
            trailers={"Entry-Id": entry.id},
        )

    def put_bucket(self, bucket: Bucket, actor: Actor) -> str:
        before = next((b for b in self.buckets() if b.id == bucket.id), None)

        def mutate() -> list[str]:
            buckets = [b for b in self.buckets() if b.id != bucket.id]
            buckets.append(bucket)
            self._write_buckets(buckets)
            return [BUCKETS_PATH]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"bucket: {describe_bucket_change(before, bucket)}",
            trailers={},
        )

    def reorder_buckets(self, order: list[tuple[str, str | None]], actor: Actor) -> str:
        """Put buckets in a given sequence of (id, group), in a single commit.

        A drag can change the position of every bucket it passes, and all of a person's
        buckets live in one file — so writing them one at a time meant N commits rewriting the
        same file, each with its own fetch and push. It is the same shape auto-assign had.

        Deliberately **cannot** create, delete, rename or retarget anything: it sets group and
        position and nothing else. A wholesale replace would be more general, but it would also
        let a client holding a stale list silently undo somebody else's rename, or drop a
        bucket that entries still reference. Position is the only thing a drag means.

        Buckets left out are untouched — archived ones are not on screen to be dragged, and
        omitting them must not move them.
        """
        current = {bucket.id: bucket for bucket in self.buckets()}
        unknown = [bucket_id for bucket_id, _ in order if bucket_id not in current]
        if unknown:
            raise DataError(f"no such bucket: {', '.join(sorted(unknown))}")

        # Position is per group, so the index has to restart for each one rather than being
        # the position in the flat list.
        seen: dict[str | None, int] = {}
        moved: dict[str, Bucket] = {}
        for bucket_id, group in order:
            index = seen.get(group, 0)
            seen[group] = index + 1
            moved[bucket_id] = current[bucket_id].model_copy(
                update={"group": group, "order": index}
            )

        def mutate() -> list[str]:
            self._write_buckets([moved.get(b.id, b) for b in self.buckets()])
            return [BUCKETS_PATH]

        changed = [
            current[bucket_id].name
            for bucket_id, bucket in moved.items()
            if current[bucket_id].group != bucket.group or current[bucket_id].order != bucket.order
        ]
        if not changed:
            return self.repo.head_sha()  # nothing moved; not an error

        return self._commit(
            mutate,
            actor=actor,
            subject=f"bucket: reorder {_describe_names(changed)}",
            trailers={},
        )

    def assign(self, person: str, month: str, bucket: str, amount: Decimal, actor: Actor) -> str:
        return self.assign_many(person, month, {bucket: amount}, actor)

    def assign_many(
        self, person: str, month: str, amounts: dict[str, Decimal], actor: Actor
    ) -> str:
        """Set several of one person's envelopes for a month, in a single commit."""
        return self.assign_across({person: amounts}, month, actor)

    def assign_across(
        self, funding: dict[str, dict[str, Decimal]], month: str, actor: Actor
    ) -> str:
        """Set envelopes for several people at once, in a single commit.

        Each person's funding is one file, so this touches one file per person and commits
        them together. Writing them separately meant a full fetch, commit and push each:
        filling four people's share of eight buckets was thirty-two round trips, and thirty-two
        commits for one button press.

        Committing them together also matters for correctness, not just speed. Funding a
        bucket in the agreed ratio is one decision, and a repo that briefly holds one person's
        contribution and not the others' shows an envelope that nobody chose to leave that way.
        """
        names = {bucket.id: bucket.name for bucket in self.buckets()}
        # Read before the write: the subject describes a change, and the old figures do not
        # survive it.
        before = {
            who: (yamlio.load(self.repo.read(assignments_path(who, month))) or {})
            for who in funding
        }

        def mutate() -> list[str]:
            touched: list[str] = []
            for who, amounts in funding.items():
                path = assignments_path(who, month)
                current: dict[str, Decimal] = yamlio.load(self.repo.read(path)) or {}
                for bucket_id, amount in amounts.items():
                    if amount == ZERO:
                        current.pop(bucket_id, None)  # an empty envelope is absence, not a zero
                    else:
                        current[bucket_id] = amount
                self.repo.write(path, yamlio.dump(dict(sorted(current.items()))))
                touched.append(path)
            return touched

        if len(funding) == 1:
            who, amounts = next(iter(funding.items()))
            described = f"{_describe_assignment(amounts, before[who], names)} for {month} ({who})"
            trailers = {"Person": who, "Month": month}
        else:
            changed = sorted(
                {
                    names.get(bucket_id, bucket_id)
                    for who, amounts in funding.items()
                    for bucket_id, amount in amounts.items()
                    if amount != before[who].get(bucket_id, ZERO)
                }
            )
            described = f"{_describe_names(changed)} for {month} ({len(funding)} funders)"
            trailers = {"Month": month}

        return self._commit(mutate, actor=actor, subject=f"assign: {described}", trailers=trailers)

    def put_scheduled(self, items: list[Scheduled], actor: Actor) -> str:
        before = [item.name for item in self.scheduled()]

        def mutate() -> list[str]:
            if items:
                self.repo.write(
                    SCHEDULED_PATH,
                    yamlio.dump(
                        [item.model_dump(mode="python", exclude_none=True) for item in items]
                    ),
                )
            else:
                self.repo.delete(SCHEDULED_PATH)
            return [SCHEDULED_PATH]

        return self._commit(
            mutate,
            actor=actor,
            subject=(
                "scheduled: "
                f"{describe_list_change(before, [i.name for i in items], 'recurring entry')}"
            ),
            trailers={},
        )

    def convert_entries(
        self,
        conversions: list[tuple[Entry, Fx]],
        actor: Actor,
        subject: str,
        rate_row: RateRow | None = None,
    ) -> str:
        """Attach `fx` to several entries in one commit.

        One commit whether it is one entry or a whole bucket's worth: a bucket half converted
        is a state nobody chose, and the subject says what rate was applied to what.
        """
        if not conversions:
            return self.repo.head_sha()
        for entry, _ in conversions:
            if entry.fx is not None:
                raise DataError(f"entry {entry.id} is already converted; undo that instead")

        def mutate() -> list[str]:
            by_month: dict[str, dict[str, Fx]] = {}
            for entry, fx in conversions:
                by_month.setdefault(entry.month, {})[entry.id] = fx
            touched: list[str] = []
            for month, fx_by_id in by_month.items():
                current = self.entries_for_month(month)
                self._write_ledger(
                    month,
                    [
                        e.model_copy(update={"fx": fx_by_id[e.id]}) if e.id in fx_by_id else e
                        for e in current
                    ],
                )
                touched.append(ledger_path(month))
            return [*touched, *self._record_rate(rate_row)]

        trailers = {"Entry-Id": conversions[0][0].id} if len(conversions) == 1 else {}
        return self._commit(mutate, actor=actor, subject=subject, trailers=trailers)

    def post_scheduled(
        self, entry: Entry, scheduled_id: str, actor: Actor, rate_row: RateRow | None = None
    ) -> str:
        """Create the entry a recurrence is due for, and record that it was posted.

        Both in one commit: if the entry landed but the marker did not, the same charge would
        be offered again and posted twice.
        """

        def mutate() -> list[str]:
            entries = self.entries_for_month(entry.month)
            if any(existing.id == entry.id for existing in entries):
                raise DataError(f"entry {entry.id} already exists")
            self._write_ledger(entry.month, [*entries, entry])

            items = self.scheduled()
            found = next((item for item in items if item.id == scheduled_id), None)
            if found is None:
                raise DataError(f"no scheduled entry {scheduled_id!r}")
            updated = [
                item.model_copy(update={"last_posted": entry.date})
                if item.id == scheduled_id
                else item
                for item in items
            ]
            self.repo.write(
                SCHEDULED_PATH,
                yamlio.dump(
                    [item.model_dump(mode="python", exclude_none=True) for item in updated]
                ),
            )
            return [ledger_path(entry.month), SCHEDULED_PATH, *self._record_rate(rate_row)]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"entry: post {entry.payee} {abs(entry.amount):.2f} {entry.currency}",
            trailers={"Entry-Id": entry.id, "Scheduled": scheduled_id},
        )

    def revert(self, sha: str, actor: Actor) -> str:
        """Undo one commit by committing its inverse.

        Goes through the same lock, rebase and push path as every other write, because an
        undo racing a concurrent edit is exactly as dangerous as two edits racing.
        """
        with write_lock(self.repo):
            self.repo.ensure_clone(actor.token)
            try:
                new_sha = self.repo.revert(
                    sha,
                    actor.token,
                    f"revert: {sha[:7]}\n\nActor: {actor.login}\nReverts: {sha}\n",
                )
            except Exception as exc:
                # A revert that does not apply cleanly means the change has been built on
                # since. Undoing it blindly would silently discard the later work.
                raise DataError(
                    f"cannot undo {sha[:7]} cleanly — later changes depend on it"
                ) from exc

            try:
                self.repo.push(actor.token)
            except PushRejected:
                self.repo.rebase_onto_remote(actor.token)
                self.repo.push(actor.token)
                new_sha = self.repo.head_sha()
            return new_sha

    def put_note(self, entry_id: str, text: str, actor: Actor) -> str:
        def mutate() -> list[str]:
            if text.strip():
                self.repo.write(note_path(entry_id), text.rstrip() + "\n")
            else:
                self.repo.delete(note_path(entry_id))  # an empty note is absence, not a file
            return [note_path(entry_id)]

        return self._commit(
            mutate,
            actor=actor,
            subject=(
                f"note: {'update' if text.strip() else 'remove'} on "
                f"{found[0].payee if (found := self.find_entry(entry_id)) else entry_id}"
            ),
            trailers={"Entry-Id": entry_id},
        )

    def add_comment(self, entry_id: str, comment: Comment, actor: Actor) -> str:
        """Append one message. The file is only ever appended to or pruned, never rewritten
        into a different shape, so two people replying at once rebase cleanly."""
        found = self.find_entry(entry_id)
        if found is None:
            raise DataError(f"no entry {entry_id}")

        def mutate() -> list[str]:
            existing = self.comments(entry_id)
            self._write_comments(entry_id, [*existing, comment])
            return [comments_path(entry_id)]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"comment: {comment.author} on {found[0].payee}",
            trailers={"Entry-Id": entry_id, "Comment-Id": comment.id},
        )

    def delete_comment(self, entry_id: str, comment_id: str, actor: Actor) -> str:
        found = self.find_entry(entry_id)
        if found is None:
            raise DataError(f"no entry {entry_id}")

        def mutate() -> list[str]:
            remaining = [c for c in self.comments(entry_id) if c.id != comment_id]
            self._write_comments(entry_id, remaining)
            return [comments_path(entry_id)]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"comment: remove on {found[0].payee}",
            trailers={"Entry-Id": entry_id, "Comment-Id": comment_id},
        )

    def add_attachment(
        self, entry_id: str, name: str, content_type: str, data: bytes, actor: Actor
    ) -> str:
        """Commit one file beside an entry.

        The stored name is a ULID plus the type's extension, so two photos taken a second
        apart never collide and a person browsing the repo can still open them. The original
        filename is not kept: phones name everything IMG_4821.jpg.
        """
        found = self.find_entry(entry_id)
        if found is None:
            raise DataError(f"no entry {entry_id}")
        if content_type not in ATTACHMENT_TYPES:
            raise DataError(
                f"{content_type} is not a supported attachment type; "
                f"use one of {', '.join(sorted(ATTACHMENT_TYPES))}"
            )
        if len(data) == 0:
            raise DataError("the attachment is empty")
        if len(data) > ATTACHMENT_MAX_BYTES:
            raise DataError(
                f"the attachment is {len(data) // 1024} kB; "
                f"the limit is {ATTACHMENT_MAX_BYTES // 1024} kB"
            )

        path = attachments_prefix(entry_id) + name

        def mutate() -> list[str]:
            self.repo.write_bytes(path, data)
            return [path]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"attachment: add {name} to {found[0].payee}",
            trailers={"Entry-Id": entry_id},
        )

    def delete_attachment(self, entry_id: str, name: str, actor: Actor) -> str:
        found = self.find_entry(entry_id)
        if found is None:
            raise DataError(f"no entry {entry_id}")
        if self.attachment(entry_id, name) is None:
            raise DataError(f"no attachment {name} on entry {entry_id}")

        path = attachments_prefix(entry_id) + name

        def mutate() -> list[str]:
            self.repo.delete(path)
            return [path]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"attachment: remove {name} from {found[0].payee}",
            trailers={"Entry-Id": entry_id},
        )

    def initialize(self, budget: Budget, buckets: list[Bucket], actor: Actor) -> str:
        """Write `budget.yaml` and the first member's buckets into an empty repo.

        One commit, because a repo carrying a budget with no buckets is a state the app
        would have to explain, and it exists only between two commits nobody needs to see.

        Refuses a repo that already holds a budget rather than overwriting it: this runs
        against a repo the caller named, and a typo must not replace someone's ledger.
        """
        if self.repo.read("budget.yaml") is not None:
            raise DataError("this repo already holds a budget; connect it instead of creating")

        def mutate() -> list[str]:
            self.repo.write(
                "budget.yaml", yamlio.dump(budget.model_dump(mode="python", exclude_none=True))
            )
            self._write_buckets(buckets)
            return ["budget.yaml", BUCKETS_PATH]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"budget: create {budget.name}",
            trailers={},
        )

    def join(self, member: Member, actor: Actor) -> str:
        """Add one person to `budget.yaml` — and touch nothing else.

        Buckets are shared, so a joiner does not arrive with any: the household's already
        exist for them to file under. When this method still seeded starter buckets (a
        holdover from per-person bucket files) it REPLACED the household's entire list —
        names, targets, groups and splits — with the seven defaults, in one commit, the
        moment anybody joined. Whether the joiner bears anything is the buckets' `split`,
        which stays exactly as it was until someone edits it.
        """
        budget = self.budget()
        if any(m.person == member.person for m in budget.members):
            raise DataError(f"{member.person} is already a member of this budget")

        updated = budget.model_copy(update={"members": [*budget.members, member]})

        def mutate() -> list[str]:
            self.repo.write(
                "budget.yaml", yamlio.dump(updated.model_dump(mode="python", exclude_none=True))
            )
            return ["budget.yaml"]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"members: {member.name} joined {budget.name}",
            trailers={},
        )

    def put_members(self, budget: Budget, actor: Actor) -> str:
        before = [member.name for member in self.budget().members]

        def mutate() -> list[str]:
            self.repo.write(
                "budget.yaml", yamlio.dump(budget.model_dump(mode="python", exclude_none=True))
            )
            return ["budget.yaml"]

        return self._commit(
            mutate,
            actor=actor,
            subject=(
                "members: "
                f"{describe_list_change(before, [m.name for m in budget.members], 'member')}"
            ),
            trailers={},
        )

    # ---- internals ------------------------------------------------------------------

    def _write_buckets(self, buckets: list[Bucket]) -> None:
        """Write one person's buckets, always in display order.

        Sorting here as well as on read means the file on disk matches what the app shows,
        so someone reading the repo directly sees the same order they see on screen.
        """
        self.repo.write(
            BUCKETS_PATH,
            yamlio.dump(
                [
                    b.model_dump(mode="python", exclude_none=True)
                    for b in sorted(buckets, key=_bucket_sort_key)
                ]
            ),
        )

    def _record_rate(self, row: RateRow | None) -> list[str]:
        """Add one fetched rate to the table, if it is not there already. Returns the paths
        to stage, so a caller can fold it into its own commit."""
        if row is None:
            return []
        day, currency, rate = row
        table = self.rates()
        if table.get(day, {}).get(currency) == rate:
            return []
        table.setdefault(day, {})[currency] = rate
        self.repo.write(
            RATES_PATH,
            yamlio.dump(
                {
                    day.isoformat(): {code: str(value) for code, value in sorted(quotes.items())}
                    for day, quotes in sorted(table.items())
                }
            ),
        )
        return [RATES_PATH]

    def _write_comments(self, entry_id: str, comments: list[Comment]) -> None:
        """Oldest first, and no file at all once the last comment is gone."""
        if not comments:
            self.repo.delete(comments_path(entry_id))
            return
        self.repo.write(
            comments_path(entry_id),
            yamlio.dump(
                [
                    c.model_dump(mode="python", exclude_none=True)
                    for c in sorted(comments, key=lambda c: c.id)
                ]
            ),
        )

    def _write_ledger(self, month: str, entries: list[Entry]) -> None:
        """Write a month's entries, always sorted by (date, id).

        The stable order is what keeps two people appending on the same day from producing a
        merge conflict: each writes into the same position the other would have.
        """
        entries = sorted(entries, key=lambda e: (e.date, e.id))
        if not entries:
            self.repo.delete(ledger_path(month))
            return
        self.repo.write(
            ledger_path(month),
            yamlio.dump([e.model_dump(mode="python", exclude_none=True) for e in entries]),
        )

    def _commit(
        self,
        mutate: Callable[[], list[str]],
        *,
        actor: Actor,
        subject: str,
        trailers: dict[str, str],
    ) -> str:
        """Apply a mutation, commit it, and push. Rebases and retries once if the remote moved.

        The retry rebases the commit that was already made rather than re-running `mutate`;
        re-running it would apply the change a second time on top of itself.
        """
        body = {**trailers, "Actor": actor.login}
        message = subject + "\n\n" + "\n".join(f"{key}: {value}" for key, value in body.items())

        with write_lock(self.repo):
            self.repo.ensure_clone(actor.token)
            self.check_schema()
            paths = mutate()

            # Stamp the marker on the first write, so a repo created by hand gains one and a
            # future version has something to compare against.
            if self.repo.read(".money/schema-version") is None:
                self.repo.write(".money/schema-version", f"{SCHEMA_VERSION}\n")
                paths = [*paths, ".money/schema-version"]
            sha = self.repo.commit(
                message=message,
                author_name=actor.name,
                author_email=actor.email,
                paths=paths,
            )
            if sha is None:
                return self.repo.head_sha()  # nothing changed; not an error

            try:
                self.repo.push(actor.token)
            except PushRejected:
                # Someone committed between our clone refresh and our push. Replay our commit
                # on top of theirs. A conflict here aborts and surfaces, rather than guessing.
                self.repo.rebase_onto_remote(actor.token)
                self.repo.push(actor.token)
                sha = self.repo.head_sha()
            return sha
