"""Shared HTTP client."""

from __future__ import annotations

from typing import Any

import httpx

from collectors.common.retry import with_retry


class JsonHttpClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @with_retry()
    def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = client.get(path, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    @with_retry()
    def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
    ) -> Any:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = client.post(path, headers=headers, params=params, json=json)
            response.raise_for_status()
            return response.json()
