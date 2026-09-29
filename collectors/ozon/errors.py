"""Ozon error helpers."""

from __future__ import annotations

import httpx

# 404/405 mean the method itself is gone (Ozon answers them for switched-off API
# versions), so they must fail the task loudly instead of being logged as skipped.
_REMOVED_METHOD_STATUSES = {404, 405}


def is_capability_error(exc: Exception) -> bool:
    """True when the seller lacks access to a method (role, subscription, contract)."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    status = exc.response.status_code
    if status in _REMOVED_METHOD_STATUSES:
        return False
    if status == 403:
        return True
    body = exc.response.text.lower() if exc.response is not None else ""
    capability_hints = [
        "premium",
        "not available",
        "forbidden",
        "unsupported",
        "method unavailable",
    ]
    return any(hint in body for hint in capability_hints)
