"""Shared test setup."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def isolate_git_config() -> None:
    """Keep the developer's global git config out of the tests.

    The store sets these for its own subprocesses regardless — see `GitRepo._env`, which is
    where it matters in production. This covers the raw `git` calls the fixtures make when
    they seed a remote: without it, a developer with `core.hooksPath` set has their personal
    hooks running on every seed commit, which is slow and can fail for reasons that have
    nothing to do with this project.
    """
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
