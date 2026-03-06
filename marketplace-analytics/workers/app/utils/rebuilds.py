"""Helpers for serializing destructive rebuild jobs."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from redis import Redis

from app.utils.locking import LockHandle, lock_scope

LOGGER = logging.getLogger("workers.rebuilds")
REBUILD_PIPELINE_SOURCE = "rebuild_pipeline"
REBUILD_ACCOUNT_ID = "global"
REBUILD_LOCK_TTL_SECONDS = 7200


@contextmanager
def rebuild_task_scope(
    redis_client: Redis,
    task_lock_source: str,
    *,
    ttl_seconds: int = REBUILD_LOCK_TTL_SECONDS,
) -> Iterator[tuple[LockHandle, LockHandle]]:
    """Acquire both the shared rebuild lock and the task-specific lock."""
    with ExitStack() as stack:
        pipeline_lock = stack.enter_context(
            lock_scope(
                redis_client=redis_client,
                source=REBUILD_PIPELINE_SOURCE,
                account_id=REBUILD_ACCOUNT_ID,
                ttl_seconds=ttl_seconds,
            )
        )
        task_lock = stack.enter_context(
            lock_scope(
                redis_client=redis_client,
                source=task_lock_source,
                account_id=REBUILD_ACCOUNT_ID,
                ttl_seconds=ttl_seconds,
            )
        )
        yield pipeline_lock, task_lock
