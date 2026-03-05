"""Dependency helpers."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.db.ch import build_client


def get_app_settings() -> Settings:
    return get_settings()


def get_ch_client(settings: Settings = Depends(get_app_settings)) -> Iterator:
    client = build_client(settings)
    try:
        yield client
    finally:
        client.close()


def require_admin_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin disabled")

    if x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
