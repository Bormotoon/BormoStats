"""Ozon error helpers."""

from __future__ import annotations

import httpx


def is_capability_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    body = exc.response.text.lower() if exc.response is not None else ""
    if status in {403, 404, 405}:
        return True
    capability_hints = [
        "premium",
        "not available",
        "forbidden",
        "unsupported",
        "method unavailable",
    ]
    return any(hint in body for hint in capability_hints)
