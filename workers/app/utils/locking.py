"""Redis locking helpers for serialized collector runs."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from redis import Redis

DEFAULT_LOCK_TTL_SECONDS = 1800
LOGGER = logging.getLogger("workers.locks")


class LockNotAcquiredError(RuntimeError):
    """Raised when lock cannot be acquired before timeout."""


class LockLostError(RuntimeError):
    """Raised when a lock could not be renewed and exclusivity was lost."""


@dataclass
class LockHandle:
    key: str
    token: str
    ttl_seconds: int
    acquired_monotonic: float = field(default_factory=time.monotonic)
    renewals: int = 0
    lost: bool = False

    def held_seconds(self) -> float:
        return time.monotonic() - self.acquired_monotonic

    def ensure_held(self) -> None:
        if self.lost:
            raise LockLostError(f"lock lost for {self.key}")


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
            return LockHandle(key=lock_key, token=token, ttl_seconds=ttl_seconds)
        if wait_timeout_seconds == 0 or time.monotonic() >= deadline:
            raise LockNotAcquiredError(f"could not acquire lock {lock_key}")
        time.sleep(0.5)


def renew_lock(
    redis_client: Redis,
    lock: LockHandle,
    ttl_seconds: int | None = None,
) -> bool:
    """Renew lock TTL only if token still matches."""
    ttl = int(ttl_seconds or lock.ttl_seconds)
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('expire', KEYS[1], ARGV[2])
    else
      return 0
    end
    """
    renewed = bool(redis_client.eval(script, 1, lock.key, lock.token, ttl))
    if renewed:
        lock.renewals += 1
        LOGGER.info(
            "lock_renewed key=%s held_s=%s renewals=%s ttl_seconds=%s",
            lock.key,
            round(lock.held_seconds(), 3),
            lock.renewals,
            ttl,
        )
        return True

    lock.lost = True
    LOGGER.warning(
        "lock_renew_failed key=%s held_s=%s renewals=%s",
        lock.key,
        round(lock.held_seconds(), 3),
        lock.renewals,
    )
    return False


def release_lock(redis_client: Redis, lock: LockHandle) -> bool:
    """Release lock only if token matches."""
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    else
      return 0
    end
    """
    released = bool(redis_client.eval(script, 1, lock.key, lock.token))
    LOGGER.info(
        "lock_released key=%s held_s=%s renewals=%s released=%s",
        lock.key,
        round(lock.held_seconds(), 3),
        lock.renewals,
        released,
    )
    return released


@contextmanager
def lock_scope(
    redis_client: Redis,
    source: str,
    account_id: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    wait_timeout_seconds: int = 0,
    auto_renew: bool = False,
    renew_interval_seconds: float | None = None,
) -> Iterator[LockHandle]:
    lock = acquire_lock(
        redis_client=redis_client,
        source=source,
        account_id=account_id,
        ttl_seconds=ttl_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    )
    stop_event = threading.Event()
    renew_thread: threading.Thread | None = None

    if auto_renew:
        interval = (
            renew_interval_seconds
            if renew_interval_seconds is not None
            else max(1.0, ttl_seconds / 3)
        )

        def _renew_loop() -> None:
            while not stop_event.wait(interval):
                if not renew_lock(redis_client=redis_client, lock=lock, ttl_seconds=ttl_seconds):
                    return

        renew_thread = threading.Thread(
            target=_renew_loop,
            name=f"lock-renew:{lock.key}",
            daemon=True,
        )
        renew_thread.start()

    try:
        yield lock
    finally:
        stop_event.set()
        if renew_thread is not None:
            renew_thread.join(timeout=max(1.0, renew_interval_seconds or ttl_seconds / 3))
        release_lock(redis_client=redis_client, lock=lock)
