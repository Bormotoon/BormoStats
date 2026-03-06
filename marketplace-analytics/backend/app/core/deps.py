"""Dependency helpers."""

from __future__ import annotations

from functools import lru_cache

import clickhouse_connect
from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


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


def require_admin_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin disabled")

    if x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
