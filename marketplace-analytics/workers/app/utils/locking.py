"""Redis locking helpers for serialized collector runs."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from redis import Redis

DEFAULT_LOCK_TTL_SECONDS = 1800


class LockNotAcquired(RuntimeError):
    """Raised when lock cannot be acquired before timeout."""


@dataclass(frozen=True)
class LockHandle:
    key: str
    token: str


def build_lock_key(source: str, account_id: str) -> str:
    return f"lock:{source}:{account_id}"


def acquire_lock(
    redis_client: Redis,
    source: str,
    account_id: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    wait_timeout_seconds: int = 0,
) -> LockHandle:
    """Acquire lock with optional waiting window."""
    lock_key = build_lock_key(source=source, account_id=account_id)
    token = uuid.uuid4().hex
    deadline = time.monotonic() + wait_timeout_seconds

    while True:
        acquired = redis_client.set(lock_key, token, ex=ttl_seconds, nx=True)
        if acquired:
            return LockHandle(key=lock_key, token=token)
        if wait_timeout_seconds == 0 or time.monotonic() >= deadline:
            raise LockNotAcquired(f"could not acquire lock {lock_key}")
        time.sleep(0.5)


def release_lock(redis_client: Redis, lock: LockHandle) -> None:
    """Release lock only if token matches."""
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    else
      return 0
    end
    """
    redis_client.eval(script, 1, lock.key, lock.token)


@contextmanager
def lock_scope(
    redis_client: Redis,
    source: str,
    account_id: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    wait_timeout_seconds: int = 0,
) -> Iterator[LockHandle]:
    lock = acquire_lock(
        redis_client=redis_client,
        source=source,
        account_id=account_id,
        ttl_seconds=ttl_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    )
    try:
        yield lock
    finally:
        release_lock(redis_client=redis_client, lock=lock)
