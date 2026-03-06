"""Dependency helpers."""

from __future__ import annotations

from functools import lru_cache

import clickhouse_connect
import structlog
from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.models.admin import AdminRequestContext

LOGGER = structlog.get_logger(__name__)


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def _get_cached_ch_client(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
) -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
    )


def get_ch_client(
    settings: Settings = Depends(get_app_settings),
) -> clickhouse_connect.driver.Client:
    return _get_cached_ch_client(
        host=settings.ch_host,
        port=settings.ch_port,
        user=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_db,
    )


def get_admin_request_context(request: Request) -> AdminRequestContext:
    client_host = request.client.host if request.client is not None else "unknown"
    return AdminRequestContext(
        path=request.url.path,
        method=request.method,
        remote_addr=client_host,
        forwarded_for=request.headers.get("X-Forwarded-For"),
        user_agent=request.headers.get("User-Agent"),
    )


def require_admin_api_key(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not settings.admin_api_key:
        LOGGER.warning(
            "admin_request_rejected",
            reason="admin_disabled",
            path=request.url.path,
            method=request.method,
            remote_addr=request.client.host if request.client is not None else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin disabled",
        )

    if x_api_key != settings.admin_api_key:
        LOGGER.warning(
            "admin_request_rejected",
            reason="invalid_api_key",
            path=request.url.path,
            method=request.method,
            remote_addr=request.client.host if request.client is not None else "unknown",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
