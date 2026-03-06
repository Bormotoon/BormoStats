from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import collectors.common.http_client as http_client_module
from collectors.common.http_client import CircuitOpenError, JsonHttpClient
from collectors.common.retry import wb_retry_delay_seconds
from collectors.ozon.errors import is_capability_error


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


def _build_http_client(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[httpx.Response | Exception],
    *,
    marketplace: str = "generic",
    max_attempts: int = 3,
) -> tuple[JsonHttpClient, list[float], list[str]]:
    sleeps: list[float] = []
    request_urls: list[str] = []
    pending = list(outcomes)

    monkeypatch.setattr(http_client_module, "sleep_seconds", lambda delay: sleeps.append(delay))
    monkeypatch.setattr(
        http_client_module,
        "exponential_jitter_delay_seconds",
        lambda attempt: float(attempt),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        outcome = pending.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = JsonHttpClient(
        "https://example.test",
        marketplace=marketplace,
        max_attempts=max_attempts,
    )
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=client.base_url,
        timeout=client.timeout,
    )
    return client, sleeps, request_urls


def test_http_client_retries_429(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = httpx.Request("GET", "https://example.test/orders")
    retry_response = httpx.Response(status_code=429, request=request, json={"detail": "slow down"})
    success_response = httpx.Response(status_code=200, request=request, json={"items": [1]})
    client, sleeps, request_urls = _build_http_client(
        monkeypatch,
        [retry_response, success_response],
        max_attempts=3,
    )

    with caplog.at_level(logging.WARNING, logger="collectors.http"):
        payload = client.get("/orders")

    try:
        assert payload == {"items": [1]}
        assert request_urls == ["https://example.test/orders", "https://example.test/orders"]
        assert sleeps == [1.0]
        assert "reason=throttled" in caplog.text
    finally:
        client.close()


def test_http_client_retries_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = httpx.Request("GET", "https://example.test/orders")
    retry_response = httpx.Response(status_code=500, request=request, json={"detail": "oops"})
    success_response = httpx.Response(status_code=200, request=request, json={"items": [1]})
    client, sleeps, request_urls = _build_http_client(
        monkeypatch,
        [retry_response, success_response],
        max_attempts=3,
    )

    with caplog.at_level(logging.WARNING, logger="collectors.http"):
        payload = client.get("/orders")

    try:
        assert payload == {"items": [1]}
        assert request_urls == ["https://example.test/orders", "https://example.test/orders"]
        assert sleeps == [1.0]
        assert "reason=server_error" in caplog.text
    finally:
        client.close()


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_http_client_does_not_retry_non_retryable_4xx(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = httpx.Request("GET", "https://example.test/orders")
    response = httpx.Response(
        status_code=status_code,
        request=request,
        json={"detail": "bad request"},
    )
    client, sleeps, request_urls = _build_http_client(monkeypatch, [response], max_attempts=3)

    with caplog.at_level(logging.WARNING, logger="collectors.http"):
        with pytest.raises(httpx.HTTPStatusError):
            client.get("/orders")

    try:
        assert request_urls == ["https://example.test/orders"]
        assert sleeps == []
        assert "reason=client_error" in caplog.text
    finally:
        client.close()


def test_http_client_does_not_retry_when_circuit_is_open(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, sleeps, request_urls = _build_http_client(monkeypatch, [], max_attempts=3)
    client._open_until = datetime.now(UTC) + timedelta(seconds=30)

    with caplog.at_level(logging.WARNING, logger="collectors.http"):
        with pytest.raises(CircuitOpenError):
            client.get("/orders")

    try:
        assert request_urls == []
        assert sleeps == []
        assert "reason=circuit_open" in caplog.text
    finally:
        client.close()
