"""Dependency helpers.

The ClickHouse client is owned by the application lifespan (see ``app.main``):
it is created on startup, stored on ``app.state`` and closed on shutdown. A lazy
fallback keeps tooling that instantiates the app without lifespan working.
"""

from __future__ import annotations

import threading
import time
from typing import Annotated, Any

import clickhouse_connect
import structlog
from app.core.config import Settings, get_settings
from app.db.ch import build_raw_client
from app.models.admin import AdminRequestContext
from fastapi import Depends, FastAPI, Request
from prometheus_client import Counter, Histogram

LOGGER = structlog.get_logger(__name__)

CLICKHOUSE_QUERY_SECONDS = Histogram(
    "backend_clickhouse_query_duration_seconds",
    "Latency of ClickHouse calls issued by the backend",
    ["operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
CLICKHOUSE_QUERY_ERRORS = Counter(
    "backend_clickhouse_query_errors_total",
    "ClickHouse calls issued by the backend that raised an error",
    ["operation"],
)

_CLIENT_LOCK = threading.Lock()


def get_app_settings() -> Settings:
    return get_settings()


def _instrument(client: clickhouse_connect.driver.Client) -> clickhouse_connect.driver.Client:
    for operation in ("query", "command", "insert"):
        original = getattr(client, operation)

        def timed(
            *args: Any, _original: Any = original, _op: str = operation, **kwargs: Any
        ) -> Any:
            started = time.perf_counter()
            try:
                return _original(*args, **kwargs)
            except Exception:
                CLICKHOUSE_QUERY_ERRORS.labels(operation=_op).inc()
                raise
            finally:
                CLICKHOUSE_QUERY_SECONDS.labels(operation=_op).observe(
                    time.perf_counter() - started
                )

        setattr(client, operation, timed)
    return client


def create_ch_client(settings: Settings) -> clickhouse_connect.driver.Client:
    return _instrument(
        build_raw_client(
            host=settings.ch_host,
            port=settings.ch_port,
            username=settings.ch_user,
            password=settings.ch_password,
            database=settings.ch_db,
            pool_maxsize=settings.ch_pool_maxsize,
            connect_timeout=settings.ch_connect_timeout_seconds,
            query_timeout=settings.ch_query_timeout_seconds,
        )
    )


def open_ch_client(app: FastAPI, settings: Settings) -> clickhouse_connect.driver.Client:
    with _CLIENT_LOCK:
        client: clickhouse_connect.driver.Client | None = getattr(app.state, "ch_client", None)
        if client is None:
            client = create_ch_client(settings)
            app.state.ch_client = client
        return client


def close_ch_client(app: FastAPI) -> None:
    with _CLIENT_LOCK:
        client: clickhouse_connect.driver.Client | None = getattr(app.state, "ch_client", None)
        app.state.ch_client = None
    if client is not None:
        try:
            client.close()
        except Exception as exc:
            LOGGER.warning("clickhouse_client_close_failed", error=str(exc))


def get_ch_client(
    request: Request,
    settings: Settings = Depends(get_app_settings),
) -> clickhouse_connect.driver.Client:
    return open_ch_client(request.app, settings)


def get_admin_request_context(request: Request) -> AdminRequestContext:
    client_host = request.client.host if request.client is not None else "unknown"
    return AdminRequestContext(
        path=request.url.path,
        method=request.method,
        remote_addr=client_host,
        forwarded_for=request.headers.get("X-Forwarded-For"),
        user_agent=request.headers.get("User-Agent"),
        request_id=getattr(request.state, "request_id", None),
    )


ChClientDependency = Annotated[clickhouse_connect.driver.Client, Depends(get_ch_client)]
SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
AdminRequestContextDependency = Annotated[
    AdminRequestContext,
    Depends(get_admin_request_context),
]
