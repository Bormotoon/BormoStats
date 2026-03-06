from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
LOCKING_PATH = ROOT_DIR / "workers" / "app" / "utils" / "locking.py"

SPEC = importlib.util.spec_from_file_location("worker_locking", LOCKING_PATH)
assert SPEC is not None
assert SPEC.loader is not None
worker_locking = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker_locking
SPEC.loader.exec_module(worker_locking)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expire_calls: list[tuple[str, int]] = []
        self._guard = threading.Lock()

    def set(self, key: str, token: str, ex: int, nx: bool) -> bool:
        del ex, nx
        with self._guard:
            if key in self.values:
                return False
            self.values[key] = token
            return True

    def eval(self, script: str, count: int, *args: object) -> int:
        del script, count
        with self._guard:
            if len(args) == 2:
                key, token = args
                if self.values.get(str(key)) == str(token):
                    del self.values[str(key)]
                    return 1
                return 0
            if len(args) == 3:
                key, token, ttl = args
                if self.values.get(str(key)) == str(token):
                    self.expire_calls.append((str(key), int(ttl)))
                    return 1
                return 0
        raise AssertionError(f"unexpected eval args: {args}")


def test_lock_scope_auto_renews_and_emits_telemetry(caplog) -> None:
    redis_client = FakeRedis()

    with caplog.at_level(logging.INFO, logger="workers.locks"):
        with worker_locking.lock_scope(
            redis_client=redis_client,
            source="wb_sales",
            account_id="acc-1",
            ttl_seconds=1,
            auto_renew=True,
            renew_interval_seconds=0.05,
        ) as lock:
            time.sleep(0.16)
            lock.ensure_held()
            assert lock.renewals >= 1

    assert redis_client.values == {}
    assert redis_client.expire_calls
    assert "lock_renewed" in caplog.text
    assert "lock_released" in caplog.text


def test_release_foreign_lock_is_rejected_after_renewal() -> None:
    redis_client = FakeRedis()
    lock = worker_locking.acquire_lock(redis_client, "wb_sales", "acc-1", ttl_seconds=30)

    assert worker_locking.renew_lock(redis_client, lock, ttl_seconds=30) is True

    foreign_lock = worker_locking.LockHandle(
        key=lock.key,
        token="foreign-token",
        ttl_seconds=30,
    )
    assert worker_locking.release_lock(redis_client, foreign_lock) is False
    assert redis_client.values[lock.key] == lock.token

    assert worker_locking.release_lock(redis_client, lock) is True
    assert lock.key not in redis_client.values
