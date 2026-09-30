"""Read-through Redis cache for analytics query results.

Results are stored as JSON (never pickle, so a tampered Redis cannot execute code)
under a digest of the query name and its parameters, which always include the
organization. One ``MGET`` fetches the entry together with the current generation
(see ``common.query_cache``); an entry from an older generation is a miss.

The cache fails open: any Redis error is logged, counted, and the cache stays off
for ``_ERROR_BACKOFF_SECONDS`` so a Redis outage costs at most one short timeout.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from typing import Any, cast

import structlog
from fastapi.encoders import jsonable_encoder
from prometheus_client import Counter
from redis import Redis

from common.query_cache import GENERATION_KEY, bump_generation, entry_key

LOGGER = structlog.get_logger(__name__)

QUERY_CACHE_REQUESTS = Counter(
    "backend_query_cache_requests_total",
    "Analytics query cache lookups by result",
    ["query", "result"],
)

_ERROR_BACKOFF_SECONDS = 30.0
_SOCKET_TIMEOUT_SECONDS = 0.25

Rows = list[dict[str, Any]]


def _digest(query_name: str, parameters: dict[str, Any]) -> str:
    payload = json.dumps(
        {"query": query_name, "params": jsonable_encoder(parameters)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class QueryCache:
    def __init__(self, redis_client: Redis, *, ttl_seconds: int, max_entry_bytes: int) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._max_entry_bytes = max_entry_bytes
        self._lock = threading.Lock()
        self._disabled_until = 0.0

    @classmethod
    def from_url(cls, url: str, *, ttl_seconds: int, max_entry_bytes: int) -> QueryCache:
        client = Redis.from_url(
            url,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
        return cls(client, ttl_seconds=ttl_seconds, max_entry_bytes=max_entry_bytes)

    def _available(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._disabled_until

    def _fail(self, operation: str, query_name: str, exc: Exception) -> None:
        with self._lock:
            self._disabled_until = time.monotonic() + _ERROR_BACKOFF_SECONDS
        QUERY_CACHE_REQUESTS.labels(query=query_name, result="error").inc()
        LOGGER.warning(
            "query_cache_unavailable",
            operation=operation,
            query=query_name,
            error=str(exc),
            exception_type=type(exc).__name__,
            backoff_seconds=_ERROR_BACKOFF_SECONDS,
        )

    def get_or_compute(
        self,
        query_name: str,
        parameters: dict[str, Any],
        compute: Callable[[], Rows],
    ) -> Rows:
        """Return cached rows (JSON-compatible) or compute, store and return them."""
        if not self._available():
            QUERY_CACHE_REQUESTS.labels(query=query_name, result="bypass").inc()
            return compute()

        key = entry_key(_digest(query_name, parameters))
        try:
            generation_raw, entry_raw = cast(list[Any], self._redis.mget([GENERATION_KEY, key]))
        except Exception as exc:
            self._fail("read", query_name, exc)
            return compute()

        generation = int(generation_raw or 0)
        if entry_raw is not None:
            try:
                entry = json.loads(entry_raw)
            except ValueError:
                entry = None
            if isinstance(entry, dict) and entry.get("generation") == generation:
                QUERY_CACHE_REQUESTS.labels(query=query_name, result="hit").inc()
                rows: Rows = entry["rows"]
                return rows

        QUERY_CACHE_REQUESTS.labels(query=query_name, result="miss").inc()
        # Encode before storing so a hit and a miss return identical values.
        rows = jsonable_encoder(compute())
        payload = json.dumps({"generation": generation, "rows": rows}, separators=(",", ":"))
        if len(payload) > self._max_entry_bytes:
            QUERY_CACHE_REQUESTS.labels(query=query_name, result="oversize").inc()
            return rows
        try:
            self._redis.set(key, payload, ex=self._ttl)
        except Exception as exc:
            self._fail("write", query_name, exc)
        return rows

    def invalidate(self) -> None:
        bump_generation(self._redis)

    def close(self) -> None:
        self._redis.close()
