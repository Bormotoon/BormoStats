"""Simple in-memory rate limiter using token bucket algorithm."""

from __future__ import annotations

import time
from functools import lru_cache
from threading import Lock

from app.core.config import Settings
from fastapi import FastAPI, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


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


@lru_cache(maxsize=1)
def _get_public_bucket(rate: float, burst: int) -> TokenBucket:
    return TokenBucket(rate=rate, burst=burst)


@lru_cache(maxsize=1)
def _get_admin_bucket(rate: float, burst: int) -> TokenBucket:
    return TokenBucket(rate=rate, burst=burst)


def _parse_rate_limit(spec: str) -> tuple[float, int]:
    parts = spec.split("/")
    burst = int(parts[0])
    return burst / 60.0, burst


def setup_rate_limiter(app: FastAPI, settings: Settings) -> None:
    public_rate, public_burst = _parse_rate_limit(settings.rate_limit_per_minute)
    admin_rate, admin_burst = _parse_rate_limit(settings.admin_rate_limit_per_minute)

    public_bucket = _get_public_bucket(public_rate, public_burst)
    admin_bucket = _get_admin_bucket(admin_rate, admin_burst)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            path = request.url.path

            if path in ("/health", "/ready", "/metrics", "/"):
                return await call_next(request)

            bucket = admin_bucket if path.startswith("/api/v1/admin") else public_bucket
            bucket_key = "admin" if path.startswith("/api/v1/admin") else "public"

            if not bucket.consume():
                raise HTTPException(
                    status_code=429,
                    detail=f"rate limit exceeded for {bucket_key} endpoint",
                )

            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)
