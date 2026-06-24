"""Sensitive data redaction helpers."""

from __future__ import annotations

from typing import Any


def redact_token(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}***{value[-visible:]}"


def redact_mapping(data: dict[str, Any], sensitive_keys: set[str] | None = None) -> dict[str, Any]:
    keys = sensitive_keys or {"token", "api_key", "authorization", "password", "secret"}
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(s in key_lower for s in keys):
            redacted[key] = redact_token(str(value))
        else:
            redacted[key] = value
    return redacted
