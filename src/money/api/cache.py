"""A cache in front of the expensive reads.

The slow part of a request is never the arithmetic — it is reading and parsing every ledger
file in the repo to fold balances, and asking GitHub whether someone may see a budget.

Everything here is keyed by the commit sha the data came from, so a write invalidates it by
construction: the next read is against a new sha and simply misses. Nothing is ever
explicitly expired, which means there is no path where a stale balance can be served because
someone forgot to clear a key.

Redis being unreachable must never take the app down. Every operation degrades to a miss.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Long, because a key is only reachable while its sha is current. The TTL exists to reclaim
# space from shas nobody will ask for again, not to bound staleness.
DEFAULT_TTL_SECONDS = 60 * 60 * 24


class Cache:
    """Reads through to Redis when it is configured, and is a no-op when it is not."""

    def __init__(self, url: str | None) -> None:
        self._client: Any | None = None
        if not url:
            return

        try:
            import redis

            self._client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
            self._client.ping()
        except Exception as exc:  # noqa: BLE001 - any failure here means "run without a cache"
            logger.warning("cache unavailable, continuing without it: %s", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def get_or_set(
        self, key: str, produce: Callable[[], Any], ttl: int = DEFAULT_TTL_SECONDS
    ) -> Any:
        """Return the cached value for `key`, computing and storing it on a miss.

        A cache failure is logged and ignored: the value is produced either way, so the only
        cost of a broken Redis is the speed the cache was meant to buy.
        """
        if self._client is None:
            return produce()

        try:
            hit = self._client.get(key)
            if hit is not None:
                return json.loads(hit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache read failed for %s: %s", key, exc)
            return produce()

        value = produce()
        try:
            self._client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache write failed for %s: %s", key, exc)
        return value

    def invalidate_prefix(self, prefix: str) -> None:
        """Drop every key under a prefix.

        Only needed for things not keyed by a sha — repo access, which changes on GitHub
        without any commit happening here.
        """
        if self._client is None:
            return
        try:
            for key in self._client.scan_iter(match=f"{prefix}*", count=500):
                self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache invalidation failed for %s: %s", prefix, exc)


def entries_key(repo: str, branch: str, sha: str) -> str:
    return f"entries:{repo}:{branch}:{sha}"


def month_key(repo: str, branch: str, sha: str, person: str, month: str) -> str:
    return f"month:{repo}:{branch}:{sha}:{person}:{month}"


def balances_key(repo: str, branch: str, sha: str) -> str:
    return f"balances:{repo}:{branch}:{sha}"


def access_key(login: str, repo: str) -> str:
    return f"access:{login.casefold()}:{repo.casefold()}"
