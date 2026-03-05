from __future__ import annotations

import httpx

from collectors.ozon.errors import is_capability_error
from collectors.common.retry import wb_retry_delay_seconds


def test_wb_retry_delay_prefers_ratelimit_retry_header() -> None:
    response = httpx.Response(
        status_code=429,
        headers={"X-Ratelimit-Retry": "3", "X-Ratelimit-Reset": "10"},
    )
    assert wb_retry_delay_seconds(response) == 3.0


def test_wb_retry_delay_uses_ratelimit_reset_when_retry_missing() -> None:
    response = httpx.Response(status_code=429, headers={"X-Ratelimit-Reset": "7"})
    assert wb_retry_delay_seconds(response) == 7.0


def test_ozon_capability_error_detection_for_forbidden() -> None:
    request = httpx.Request("POST", "https://api-seller.ozon.ru/v1/advertising/statistics")
    response = httpx.Response(status_code=403, request=request, text="premium required")
    exc = httpx.HTTPStatusError("forbidden", request=request, response=response)
    assert is_capability_error(exc) is True
