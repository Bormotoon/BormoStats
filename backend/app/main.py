"""FastAPI application entrypoint."""

from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from app.api.v1 import (
    abc_xyz,
    accounts,
    admin,
    ads,
    ai,
    bidder,
    costs,
    exports,
    extension,
    freshness,
    funnel,
    insights,
    integrations,
    kpis,
    organizations,
    pim,
    plugin,
    pnl,
    repricer,
    sales,
    stocks,
    users,
)
from app.core.auth import ViewerAuth
from app.core.config import Settings, get_settings
from app.core.deps import close_ch_client, open_ch_client
from app.core.logging import configure_logging
from app.core.observability import ObservabilityMiddleware
from app.core.ops_metrics import OperationalMetricsRefresher
from app.core.ratelimit import setup_rate_limiter
from app.core.security import constant_time_equals
from app.models.api import ApiError, ApiErrorResponse
from app.services.integrations_service import InvalidSubscriptionError
from app.services.tenancy import AccountAccessError
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from common.secret_box import SecretBoxError

settings = get_settings()
configure_logging(settings.log_level)
LOGGER = structlog.get_logger(__name__)

API_ROUTERS = (
    sales,
    stocks,
    funnel,
    ads,
    kpis,
    admin,
    costs,
    plugin,
    ai,
    users,
    organizations,
    accounts,
    bidder,
    repricer,
    pnl,
    abc_xyz,
    extension,
    insights,
    pim,
    integrations,
    freshness,
    exports,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # The ClickHouse client is created lazily on first use (so the API can start while
    # ClickHouse is still coming up) and closed here on shutdown.
    refresher = OperationalMetricsRefresher(settings, settings.metrics_refresh_seconds)
    if settings.metrics_refresh_seconds > 0:
        refresher.start()
    try:
        yield
    finally:
        refresher.stop()
        close_ch_client(application)
        redis_client: Redis | None = getattr(application.state, "redis_client", None)
        if redis_client is not None:
            redis_client.close()
            application.state.redis_client = None


app = FastAPI(
    title="Marketplace Analytics API",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
setup_rate_limiter(app, settings)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["X-API-Key", "X-Organization-Id", "X-Request-ID", "Content-Type"],
)

for module in API_ROUTERS:
    app.include_router(module.router, prefix="/api/v1")

ui_dir = Path(__file__).resolve().parent / "ui"
ui_static = ui_dir / "dist"
if not ui_static.is_dir():
    ui_static = ui_dir
app.mount("/ui", StaticFiles(directory=ui_static, html=True), name="ui")


def _error_payload(
    *,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return ApiErrorResponse(
        detail=message,
        error=ApiError(code=code, message=message, details=details or []),
    ).model_dump(mode="json")


_HTTP_ERROR_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    503: "service_unavailable",
}


def _http_error_code(status_code: int) -> str:
    return _HTTP_ERROR_CODES.get(status_code, "http_error")


# -- Readiness ------------------------------------------------------------------------


@dataclass
class _ReadinessCache:
    checked_at: float = 0.0
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_READINESS = _ReadinessCache()


def _log_readiness_failure(service: str, exc: Exception) -> None:
    LOGGER.warning(
        "readiness_check_failed",
        service=service,
        error=str(exc),
        exception_type=type(exc).__name__,
    )


def _check_clickhouse(cfg: Settings) -> None:
    # Reuse the application's pooled client: this verifies the pool the API uses.
    open_ch_client(app, cfg).query("SELECT 1")


_REDIS_LOCK = threading.Lock()


def _check_redis(cfg: Settings) -> None:
    with _REDIS_LOCK:
        redis_client: Redis | None = getattr(app.state, "redis_client", None)
        if redis_client is None:
            redis_client = Redis.from_url(
                cfg.authenticated_redis_url, socket_timeout=2, socket_connect_timeout=2
            )
            app.state.redis_client = redis_client
    redis_client.ping()


_DEPENDENCY_CHECKS: dict[str, Callable[[Settings], None]] = {
    "clickhouse": _check_clickhouse,
    "redis": _check_redis,
}


def _run_dependency_checks(cfg: Settings) -> dict[str, dict[str, Any]]:
    """Run dependency checks, reusing results for ``READINESS_CACHE_SECONDS``."""
    with _READINESS.lock:
        now = time.monotonic()
        if _READINESS.results and now - _READINESS.checked_at < cfg.readiness_cache_seconds:
            return _READINESS.results
        results: dict[str, dict[str, Any]] = {}
        for service, check in _DEPENDENCY_CHECKS.items():
            started = time.perf_counter()
            try:
                check(cfg)
                ok = True
            except Exception as exc:
                _log_readiness_failure(service, exc)
                ok = False
            results[service] = {
                "status": "ok" if ok else "fail",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        _READINESS.results = results
        _READINESS.checked_at = now
        return results


def reset_readiness_cache() -> None:
    with _READINESS.lock:
        _READINESS.results = {}
        _READINESS.checked_at = 0.0


# -- Exception handlers ------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    LOGGER.info(
        "api_request_validation_failed",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )
    details = [
        {
            "loc": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            code="validation_error", message="validation failed", details=details
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    LOGGER.info(
        "api_http_exception",
        path=request.url.path,
        method=request.method,
        status_code=exc.status_code,
        detail=exc.detail,
    )
    message = exc.detail if isinstance(exc.detail, str) else "request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(code=_http_error_code(exc.status_code), message=message),
        headers=exc.headers,
    )


@app.exception_handler(AccountAccessError)
async def account_access_exception_handler(
    request: Request, exc: AccountAccessError
) -> JSONResponse:
    LOGGER.warning("account_access_denied", path=request.url.path, detail=str(exc))
    return JSONResponse(
        status_code=403,
        content=_error_payload(code="forbidden", message=str(exc)),
    )


@app.exception_handler(InvalidSubscriptionError)
async def invalid_subscription_exception_handler(
    request: Request, exc: InvalidSubscriptionError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload(code="validation_error", message=str(exc)),
    )


@app.exception_handler(SecretBoxError)
async def secret_box_exception_handler(request: Request, exc: SecretBoxError) -> JSONResponse:
    LOGGER.error("secret_box_unavailable", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=503,
        content=_error_payload(
            code="service_unavailable", message="secret encryption is not configured"
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception(
        "api_unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(code="internal_error", message="internal server error"),
    )


# -- Health, metrics, schema --------------------------------------------------------------


@app.get("/health")
@app.get("/health/live")
def health() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@app.get("/ready")
@app.get("/health/ready")
def ready() -> dict[str, str]:
    """Readiness: ClickHouse and Redis reachable (cached for a few seconds)."""
    results = _run_dependency_checks(settings)
    if any(item["status"] != "ok" for item in results.values()):
        raise HTTPException(status_code=503, detail="service not ready")
    return {"status": "ready"}


@app.get("/health/dependencies")
def dependencies() -> JSONResponse:
    """Per-dependency status and latency for dashboards; no error details are exposed."""
    results = _run_dependency_checks(settings)
    healthy = all(item["status"] == "ok" for item in results.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "dependencies": results},
    )


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """Prometheus metrics. Gauges are refreshed in the background, so this is O(1)."""
    token = settings.metrics_bearer_token
    if token:
        header = request.headers.get("Authorization", "")
        provided = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        if not provided or not constant_time_equals(provided, token):
            raise HTTPException(
                status_code=401,
                detail="unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/openapi.json", include_in_schema=False)
def openapi_schema(auth: ViewerAuth) -> JSONResponse:
    """OpenAPI contract for API version 1; available to authenticated principals only."""
    if not settings.openapi_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    return JSONResponse(app.openapi())


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")
