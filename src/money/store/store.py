"""Reading and writing budget state as files in a git repo.

Every mutation is one commit. There is no batching, because a change that does not appear in
`git log` is a change the user cannot audit.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from money.domain.models import Budget, Bucket, Entry
from money.domain.rules import Rule
from money.store import yamlio
from money.store.gitrepo import Commit, GitRepo, PushRejected, write_lock

SCHEMA_VERSION = 1

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


def buckets_path(person: str) -> str:
    return f"people/{person}/buckets.yaml"


def assignments_path(person: str, month: str) -> str:
    return f"people/{person}/assignments/{month}.yaml"


class BudgetStore:
    def __init__(self, repo: GitRepo) -> None:
        self.repo = repo

    # ---- reads ----------------------------------------------------------------------

    def budget(self) -> Budget:
        raw = yamlio.load(self.repo.read("budget.yaml"))
        if raw is None:
            raise DataError("budget.yaml is missing; this repo is not initialized as a budget")
        return Budget.model_validate(raw)

    def rules(self) -> list[Rule]:
        raw = yamlio.load(self.repo.read("rules.yaml")) or []
        return [Rule.model_validate(item) for item in raw]

    def buckets(self, person: str) -> list[Bucket]:
        raw = yamlio.load(self.repo.read(buckets_path(person))) or []
        return [Bucket.model_validate(item) for item in raw]

    def entries_for_month(self, month: str) -> list[Entry]:
        raw = yamlio.load(self.repo.read(ledger_path(month)))
        if raw is None:
            return []  # a month with no spending simply has no file
        if not isinstance(raw, list):
            raise DataError(f"{ledger_path(month)} must contain a list of entries")
        return [Entry.model_validate(item) for item in raw]

    def all_entries(self) -> list[Entry]:
        """Every entry, in ledger order. Balances need the whole history to be correct."""
        entries: list[Entry] = []
        for path in self.repo.list_files("ledger/"):
            month = path.removeprefix("ledger/").removesuffix(".yaml")
            entries.extend(self.entries_for_month(month))
        return entries

    def assignments(self, person: str) -> dict[str, dict[str, Decimal]]:
        result: dict[str, dict[str, Decimal]] = {}
        for path in self.repo.list_files(f"people/{person}/assignments/"):
            month = path.rsplit("/", 1)[-1].removesuffix(".yaml")
            result[month] = yamlio.load(self.repo.read(path)) or {}
        return result

    def find_entry(self, entry_id: str) -> tuple[Entry, str] | None:
        """Locate an entry and the month whose file holds it."""
        for path in self.repo.list_files("ledger/"):
            month = path.removeprefix("ledger/").removesuffix(".yaml")
            for entry in self.entries_for_month(month):
                if entry.id == entry_id:
                    return entry, month
        return None

    def history(self, entry_id: str, limit: int = 50) -> list[Commit]:
        """Commits that touched one entry, found by its `Entry-Id` trailer."""
        return self.repo.log(grep=f"Entry-Id: {entry_id}", limit=limit)

    # ---- writes ---------------------------------------------------------------------

    def add_entry(self, entry: Entry, actor: Actor) -> str:
        def mutate() -> list[str]:
            entries = self.entries_for_month(entry.month)
            if any(existing.id == entry.id for existing in entries):
                raise DataError(f"entry {entry.id} already exists")
            entries.append(entry)
            self._write_ledger(entry.month, entries)
            return [ledger_path(entry.month)]

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

    def put_bucket(self, person: str, bucket: Bucket, actor: Actor) -> str:
        def mutate() -> list[str]:
            buckets = [b for b in self.buckets(person) if b.id != bucket.id]
            buckets.append(bucket)
            buckets.sort(key=lambda b: (b.group or "", b.id))
            self.repo.write(
                buckets_path(person),
                yamlio.dump([b.model_dump(mode="python", exclude_none=True) for b in buckets]),
            )
            return [buckets_path(person)]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"bucket: {person} {bucket.id}",
            trailers={"Person": person},
        )

    def assign(self, person: str, month: str, bucket: str, amount: Decimal, actor: Actor) -> str:
        def mutate() -> list[str]:
            path = assignments_path(person, month)
            current: dict[str, Decimal] = yamlio.load(self.repo.read(path)) or {}
            if amount == Decimal("0.00"):
                current.pop(bucket, None)  # an empty envelope is absence, not a zero line
            else:
                current[bucket] = amount
            self.repo.write(path, yamlio.dump(dict(sorted(current.items()))))
            return [path]

        return self._commit(
            mutate,
            actor=actor,
            subject=f"assign: {person} {bucket} {amount:.2f} for {month}",
            trailers={"Person": person, "Month": month},
        )

    def put_rules(self, rules: list[Rule], actor: Actor) -> str:
        def mutate() -> list[str]:
            self.repo.write(
                "rules.yaml",
                yamlio.dump([r.model_dump(mode="python", exclude_none=True) for r in rules]),
            )
            return ["rules.yaml"]

        return self._commit(mutate, actor=actor, subject="rules: update defaults", trailers={})

    # ---- internals ------------------------------------------------------------------

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
            paths = mutate()
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
