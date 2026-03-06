"""Shared API error responses."""

from __future__ import annotations

from typing import Any

from app.models.api import ApiErrorResponse

API_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ApiErrorResponse, "description": "Unauthorized"},
    404: {"model": ApiErrorResponse, "description": "Not found"},
    422: {"model": ApiErrorResponse, "description": "Validation error"},
    500: {"model": ApiErrorResponse, "description": "Internal server error"},
    503: {"model": ApiErrorResponse, "description": "Service unavailable"},
}
