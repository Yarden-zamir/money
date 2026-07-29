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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# One lock per clone. Writes are read-modify-write on a shared working tree, so two requests
# touching the same budget must not interleave.
_locks: dict[Path, threading.Lock] = {}
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


def lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


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
        # Never let a stray user identity or pager leak into commits made by the service.
        env |= {"GIT_PAGER": "cat", "GIT_CONFIG_NOSYSTEM": "1"}
        if extra:
            env |= extra
        return env

    # ---- lifecycle ------------------------------------------------------------------

    def ensure_clone(self, token: str) -> None:
        """Clone if missing, then make sure the branch exists and is current.

        The clone is a cache, not a source of truth: if the directory is missing or not a
        git repo, it is simply recreated.
        """
        if not (self.path / ".git").is_dir():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _clone(self.remote, self.path, token)

        self._run("remote", "set-url", "origin", self.remote)
        self._run("fetch", "--prune", "origin", token=token)
        self._checkout_branch(token)

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

    def push(self, token: str) -> None:
        try:
            self._run("push", "origin", f"HEAD:{self.branch}", token=token)
        except GitError as exc:
            if "non-fast-forward" in exc.stderr or "fetch first" in exc.stderr:
                raise PushRejected(["push"], exc.returncode, exc.stderr) from exc
            raise

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
