"""A thin, synchronous wrapper around the `git` binary.

Shelling out to `git` rather than binding libgit2 is deliberate. The repo is meant to be
readable and editable with ordinary git, so using ordinary git here keeps the app's behaviour
identical to what a person gets at a terminal — same config, same hooks, same merge rules.
Revisit only if profiling shows process spawn cost dominating a request.

Routes that use this are declared `def`, not `async def`, so FastAPI runs them in its
threadpool and these blocking calls never stall the event loop.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# One lock per clone. Writes are read-modify-write on a shared working tree, so two requests
# touching the same budget must not interleave.
#
# Reentrant, because a write holds this lock for the whole read-modify-write and calls
# `ensure_clone` inside it — which takes the same lock to stop concurrent fetches. With a
# plain Lock that is a deadlock on every write, not an occasional one.
_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()

# Supplies the push credential over stdin-free config instead of embedding it in the remote
# URL, which would persist it in .git/config. The token stays in the environment.
_CREDENTIAL_HELPER = '!f() { echo "username=x-access-token"; echo "password=$MONEY_GIT_TOKEN"; }; f'


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {stderr.strip()}")


class PushRejected(GitError):
    """The remote moved on. The caller should rebase and retry."""


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    date: str
    subject: str
    trailers: dict[str, str]


def lock_for(path: Path) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(path, threading.RLock())


# When each clone was last fetched, so a burst of reads shares one round trip to GitHub.
# In memory rather than in Redis: it guards a local directory, so it is per-process by
# nature — another process has its own clone and must make its own decision about it.
_fetched_at: dict[Path, float] = {}


# How stale a clone may be before a read pays for a fetch.
#
# Chosen against the ten-second poll rather than as a cache tuning: one screen issues three
# reads at once, so this collapses that burst into a single fetch, while still fetching on
# every poll. Somebody else's change therefore appears just as quickly as it did before.
#
# Raising this past the poll interval would start delaying other people's changes, which is
# the one thing polling exists to do — revisit only if the poll interval changes.
READ_MAX_AGE = 3.0


class GitRepo:
    """A working clone of one data repo, checked out on one branch."""

    def __init__(self, path: Path, remote: str, branch: str) -> None:
        self.path = path
        self.remote = remote
        self.branch = branch

    # ---- plumbing -------------------------------------------------------------------

    def _run(self, *args: str, token: str | None = None, check: bool = True) -> str:
        env = None
        command = ["git", "-C", str(self.path)]
        if token is not None:
            env = {"MONEY_GIT_TOKEN": token, "GIT_TERMINAL_PROMPT": "0"}
            command += ["-c", f"credential.helper={_CREDENTIAL_HELPER}"]
        command += list(args)

        result = subprocess.run(  # noqa: S603 - fixed executable, no shell
            command,
            capture_output=True,
            text=True,
            env=self._env(env),
            timeout=120,
        )
        if check and result.returncode != 0:
            raise GitError(list(args), result.returncode, result.stderr)
        return result.stdout

    @staticmethod
    def _env(extra: dict[str, str] | None) -> dict[str, str]:
        import os

        env = dict(os.environ)
        # Run against no ambient git configuration at all.
        #
        # GIT_CONFIG_GLOBAL is the important one: without it, git reads ~/.gitconfig, and a
        # developer running the tests has their own `core.hooksPath`, so every clone,
        # checkout and commit here would execute their personal hooks. That made the suite
        # both slow and flaky, and in production it would mean the service running whatever
        # hooks the host happened to configure. The service's git behaviour must depend only
        # on what this file sets.
        env |= {
            "GIT_PAGER": "cat",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        if extra:
            env |= extra
        return env

    # ---- lifecycle ------------------------------------------------------------------

    def ensure_clone(self, token: str, max_age: float = 0.0) -> None:
        """Clone if missing, then make sure the branch exists and is current.

        The clone is a cache, not a source of truth: if the directory is missing or not a
        git repo, it is simply recreated.

        `max_age` is how stale the local clone may be before the fetch is worth paying for.
        The fetch is a network round trip to GitHub and costs about 0.9s, which dominated
        everything else the server did — reading and validating a whole budget takes 40ms by
        comparison. One screen issues three reads at once (the budget list, the month, the
        buckets), so without a window a single page load paid for that round trip three
        times, and again on every ten-second poll.

        Writes pass 0 and always fetch: a commit is rebased onto the remote, so it has to be
        looking at the real remote state rather than a recent memory of it.
        """
        if self._fetched_recently(max_age) and (self.path / ".git").is_dir():
            return

        # One fetch per repo at a time. Without this, the three reads a screen makes arrive
        # together, all see a stale clone, and all fetch — which is the cost this is meant to
        # remove, and concurrent fetches into one directory contend on git's own index lock.
        with lock_for(self.path):
            if self._fetched_recently(max_age):
                return  # someone else fetched while this call was waiting for the lock

            if not (self.path / ".git").is_dir():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                _clone(self.remote, self.path, token)

            self._run("remote", "set-url", "origin", self.remote)
            self._run("fetch", "--prune", "--tags", "--force", "origin", token=token)
            self._checkout_branch(token)
            _fetched_at[self.path] = time.monotonic()

    def _fetched_recently(self, max_age: float) -> bool:
        """Whether this clone was refreshed inside the window.

        "Never fetched" has to be `None`, not a sentinel of 0. `time.monotonic()` counts from
        boot, so on a machine that started moments ago it returns a small number — and 0 then
        reads as "fetched at boot", which is seconds rather than never. A container restarting
        onto a persistent clone would serve whatever was on disk before the restart without
        fetching once. CI caught this on a fresh runner; a long-running laptop never would.
        """
        last = _fetched_at.get(self.path)
        return max_age > 0 and last is not None and time.monotonic() - last < max_age

    def _checkout_branch(self, token: str) -> None:
        """Check out the data branch, creating it from the default branch if it is new.

        This is what makes a KitSHn PR preview work: `pr-42` is created from `main` the first
        time the preview writes, so a preview never touches production data.
        """
        remote_branches = self._run("branch", "--remotes", "--format=%(refname:short)").split()
        target = f"origin/{self.branch}"

        if target in remote_branches:
            self._run("checkout", "-B", self.branch, target)
            self._run("reset", "--hard", target)
            return

        base = self._default_branch(remote_branches)
        self._run("checkout", "-B", self.branch, base)
        self._run("push", "--set-upstream", "origin", self.branch, token=token)

    def _default_branch(self, remote_branches: list[str]) -> str:
        for candidate in ("origin/main", "origin/master"):
            if candidate in remote_branches:
                return candidate
        raise GitError(["checkout"], 1, f"no main or master branch on {self.remote}")

    # ---- reading --------------------------------------------------------------------

    def read(self, relative: str) -> str | None:
        """File contents, or None when the file does not exist.

        Absent is a normal state — a month with no entries has no ledger file — so it is not
        an error. Anything else (a directory, a permission problem) still raises.
        """
        target = self.path / relative
        if not target.exists():
            return None
        return target.read_text(encoding="utf-8")

    def list_files(self, prefix: str) -> list[str]:
        output = self._run("ls-files", "--", prefix)
        return sorted(line for line in output.splitlines() if line)

    def head_sha(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

    def log(
        self, *, path: str | None = None, grep: str | None = None, limit: int = 50
    ) -> list[Commit]:
        args = [
            "log",
            f"--max-count={limit}",
            "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%(trailers:key_value_separator=:)%x1e",
        ]
        if grep:
            args += ["--grep", grep]
        if path:
            args += ["--", path]
        return _parse_log(self._run(*args))

    # ---- writing --------------------------------------------------------------------

    def write(self, relative: str, content: str) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def delete(self, relative: str) -> None:
        target = self.path / relative
        if target.exists():
            target.unlink()

    def commit(
        self, *, message: str, author_name: str, author_email: str, paths: list[str]
    ) -> str | None:
        """Stage `paths` and commit. Returns None when nothing actually changed.

        The author is the person who made the change so `git blame` and `git shortlog`
        attribute correctly; the committer stays the service.
        """
        self._run("add", "--", *paths)
        staged = self._run("diff", "--cached", "--name-only").strip()
        if not staged:
            return None

        self._run(
            "-c",
            "user.name=money",
            "-c",
            "user.email=money@yarden-zamir.com",
            "commit",
            f"--author={author_name} <{author_email}>",
            "--message",
            message,
        )
        return self.head_sha()

    def tags(self, prefix: str = "") -> list[str]:
        output = self._run("tag", "--list", f"{prefix}*")
        return sorted(line.strip() for line in output.splitlines() if line.strip())

    def tag(self, name: str, message: str, token: str) -> None:
        """Create an annotated tag and push it.

        Annotated rather than lightweight so the tag carries who closed the month and when,
        which is the whole reason for tagging instead of writing a `closed: true` field.
        """
        self._run(
            "-c",
            "user.name=money",
            "-c",
            "user.email=money@yarden-zamir.com",
            "tag",
            "--annotate",
            "--force",
            name,
            "--message",
            message,
        )
        self._run("push", "--force", "origin", f"refs/tags/{name}", token=token)

    def delete_tag(self, name: str, token: str) -> None:
        self._run("tag", "--delete", name, check=False)
        self._run("push", "origin", f":refs/tags/{name}", token=token, check=False)

    def push(self, token: str) -> None:
        try:
            self._run("push", "origin", f"HEAD:{self.branch}", token=token)
        except GitError as exc:
            if "non-fast-forward" in exc.stderr or "fetch first" in exc.stderr:
                raise PushRejected(["push"], exc.returncode, exc.stderr) from exc
            raise

    def revert(self, sha: str, token: str, message: str) -> str:
        """Undo a commit by recording the inverse of it as a new commit.

        A revert rather than a reset: the original change stays in history, so an undo is
        itself auditable and can be undone in turn. Rewriting history would make an undo
        invisible, which is the opposite of what a shared ledger needs.
        """
        self._run(
            "-c",
            "user.name=money",
            "-c",
            "user.email=money@yarden-zamir.com",
            "revert",
            "--no-edit",
            "--no-commit",
            sha,
        )
        self._run(
            "-c",
            "user.name=money",
            "-c",
            "user.email=money@yarden-zamir.com",
            "commit",
            "--message",
            message,
        )
        return self.head_sha()

    def show_at(self, sha: str, path: str) -> str | None:
        """A file's contents as of a commit, or None if it did not exist then."""
        result = subprocess.run(  # noqa: S603 - fixed executable, no shell
            ["git", "-C", str(self.path), "show", f"{sha}:{path}"],
            capture_output=True,
            text=True,
            env=self._env(None),
            timeout=30,
        )
        return result.stdout if result.returncode == 0 else None

    def changed_files(self, sha: str) -> list[tuple[str, str, int, int]]:
        """(path, status, lines added, lines removed) for one commit.

        Two formats because git will not emit both in one pass: `--name-status` says whether
        a file appeared or vanished, `--numstat` says how much of it moved. The status letter
        is the useful half — "removed" and "modified" look identical in a line count.
        """
        statuses: dict[str, str] = {}
        for line in self._run(
            "show", "--format=", "--name-status", "-m", "--first-parent", sha
        ).splitlines():
            letter, _, path = line.partition("\t")
            if path:
                statuses[path] = {"A": "added", "D": "removed"}.get(letter[:1], "modified")

        changes: list[tuple[str, str, int, int]] = []
        for line in self._run(
            "show", "--format=", "--numstat", "-m", "--first-parent", sha
        ).splitlines():
            added, _, rest = line.partition("\t")
            removed, _, path = rest.partition("\t")
            if not path:
                continue
            # git writes "-" for binary files, which have no meaningful line count.
            changes.append(
                (
                    path,
                    statuses.get(path, "modified"),
                    int(added) if added.isdigit() else 0,
                    int(removed) if removed.isdigit() else 0,
                )
            )
        return changes

    def diff(self, sha: str, max_lines: int = 400) -> tuple[str, bool]:
        """The patch for one commit, and whether it was cut short.

        Truncated rather than streamed: this is read by a person expanding a row, and a diff
        longer than a few hundred lines is one they will scroll past rather than read. The
        flag exists so the UI can say so instead of silently showing a partial change.
        """
        text = self._run("show", "--format=", "--patch", "-m", "--first-parent", sha)
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text, False
        return "\n".join(lines[:max_lines]), True

    def files_at(self, sha: str, prefix: str) -> list[str]:
        output = self._run("ls-tree", "-r", "--name-only", sha, "--", prefix)
        return sorted(line for line in output.splitlines() if line)

    def rebase_onto_remote(self, token: str) -> None:
        self._run("fetch", "origin", self.branch, token=token)
        self._run("rebase", f"origin/{self.branch}")

    def abort_rebase(self) -> None:
        self._run("rebase", "--abort", check=False)

    def reset_hard(self) -> None:
        """Discard a half-finished write so the next request starts from a clean tree."""
        self._run("reset", "--hard", check=False)
        self._run("clean", "-fd", check=False)


def _clone(remote: str, path: Path, token: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed executable, no shell
        [
            "git",
            "-c",
            f"credential.helper={_CREDENTIAL_HELPER}",
            "clone",
            remote,
            str(path),
        ],
        capture_output=True,
        text=True,
        env=GitRepo._env({"MONEY_GIT_TOKEN": token, "GIT_TERMINAL_PROMPT": "0"}),
        timeout=300,
    )
    if result.returncode != 0:
        raise GitError(["clone", remote], result.returncode, result.stderr)


def _parse_log(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for record in output.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, author_name, author_email, when, subject, raw_trailers = record.split("\x1f")
        trailers: dict[str, str] = {}
        for line in raw_trailers.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                trailers[key.strip()] = value.strip()
        commits.append(
            Commit(
                sha=sha,
                author_name=author_name,
                author_email=author_email,
                date=when,
                subject=subject,
                trailers=trailers,
            )
        )
    return commits


@contextmanager
def write_lock(repo: GitRepo) -> Iterator[None]:
    """Serialize writes to one clone, and never leave a dirty tree behind on failure."""
    lock = lock_for(repo.path)
    with lock:
        try:
            yield
        except Exception:
            repo.abort_rebase()
            repo.reset_hard()
            raise
