"""In-memory rate limiter: a token bucket per client IP and endpoint class.

Buckets are kept per client so one noisy caller cannot exhaust the budget of
everybody else. The proxy rewrites ``X-Forwarded-For`` to the real client address
and uvicorn runs with ``--proxy-headers``, so ``request.client`` is the end user.
nginx applies an additional coarse limit in front of the backend.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock

from app.core.config import Settings
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

_EXEMPT_PATHS = frozenset({"/", "/health", "/ready", "/metrics"})
_ADMIN_PREFIXES = ("/api/v1/admin", "/api/v1/organizations", "/api/v1/integrations")
MAX_TRACKED_CLIENTS = 10_000


class TokenBucket:
    def __init__(self, rate: float, burst: int) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = Lock()

    def consume(self, tokens: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate)
            self.last_refill = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class ClientBuckets:
    """Bounded LRU of per-client token buckets."""

    def __init__(self, rate: float, burst: int, max_clients: int = MAX_TRACKED_CLIENTS) -> None:
        self.rate = rate
        self.burst = burst
        self.max_clients = max_clients
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = Lock()

    def consume(self, client_key: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(client_key)
            if bucket is None:
                bucket = TokenBucket(self.rate, self.burst)
                self._buckets[client_key] = bucket
                if len(self._buckets) > self.max_clients:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(client_key)
        return bucket.consume()


def _parse_rate_limit(spec: str) -> tuple[float, int]:
    parts = spec.split("/")
    burst = int(parts[0])
    return burst / 60.0, burst


def setup_rate_limiter(app: FastAPI, settings: Settings) -> None:
    public_buckets = ClientBuckets(*_parse_rate_limit(settings.rate_limit_per_minute))
    admin_buckets = ClientBuckets(*_parse_rate_limit(settings.admin_rate_limit_per_minute))

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            path = request.url.path

            if path in _EXEMPT_PATHS or path.startswith(("/health/", "/ui/")):
                return await call_next(request)

            is_admin = path.startswith(_ADMIN_PREFIXES)
            buckets = admin_buckets if is_admin else public_buckets
            bucket_key = "admin" if is_admin else "public"
            client_key = request.client.host if request.client else "unknown"

            if not buckets.consume(client_key):
                message = f"rate limit exceeded for {bucket_key} endpoint"
                # Exceptions raised in BaseHTTPMiddleware bypass the app's exception
                # handlers, so the standard error envelope is built here.
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": message,
                        "error": {"code": "rate_limited", "message": message, "details": []},
                    },
                    headers={"Retry-After": "60"},
                )

            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)
