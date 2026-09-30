"""Redis key layout for the backend's analytics query cache.

The backend caches read-only ClickHouse results in Redis; writers (mart rebuilds,
account reassignments) invalidate every entry at once by bumping a generation
counter. Entries remember the generation they were computed for, so a bump makes
them stale immediately and their TTL cleans them up later. Redis is also the
Celery broker, so every entry must carry a TTL.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from redis import Redis

LOGGER = logging.getLogger(__name__)

KEY_PREFIX = "bormostats:qcache:v1"
GENERATION_KEY = f"{KEY_PREFIX}:generation"


def entry_key(digest: str) -> str:
    return f"{KEY_PREFIX}:entry:{digest}"


def bump_generation(redis_client: Redis) -> int | None:
    """Invalidate all cached query results; never raises (the cache is best-effort)."""
    try:
        return int(cast(Any, redis_client.incr(GENERATION_KEY)))
    except Exception as exc:
        LOGGER.warning("query_cache_invalidation_failed error=%s", exc)
        return None
