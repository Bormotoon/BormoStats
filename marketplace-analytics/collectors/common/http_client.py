"""Shared HTTP client."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from collectors.common.redaction import redact_mapping
from collectors.common.retry import (
    exponential_jitter_delay_seconds,
    sleep_seconds,
    wb_retry_delay_seconds,
)


class CircuitOpenError(RuntimeError):
    """Raised when circuit breaker is open."""


class JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        *,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 30.0,
        write_timeout_seconds: float = 30.0,
        pool_timeout_seconds: float = 10.0,
        marketplace: str = "generic",
        max_attempts: int = 5,
        circuit_failure_threshold: int = 5,
        circuit_reset_seconds: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(
            timeout=timeout_seconds,
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=write_timeout_seconds,
            pool=pool_timeout_seconds,
        )
        self.marketplace = marketplace
        self.max_attempts = max(1, max_attempts)
        self.circuit_failure_threshold = max(1, circuit_failure_threshold)
        self.circuit_reset_seconds = max(1, circuit_reset_seconds)
        self._failure_count = 0
        self._open_until: datetime | None = None
        self._logger = logging.getLogger("collectors.http")
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        self._closed = False

    def __enter__(self) -> JsonHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._client.close()
        self._closed = True

    def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("GET", path, headers=headers, params=params, json_body=None)

    def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
    ) -> Any:
        return self._request("POST", path, headers=headers, params=params, json_body=json)

    def _check_circuit(self) -> None:
        if self._open_until is None:
            return
        if datetime.now(UTC) >= self._open_until:
            self._open_until = None
            self._failure_count = 0
            return
        raise CircuitOpenError(
            f"circuit_open marketplace={self.marketplace} until={self._open_until.isoformat()}"
        )

    def _record_success(self) -> None:
        self._failure_count = 0
        self._open_until = None

    def _record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.circuit_failure_threshold:
            self._open_until = datetime.now(UTC) + timedelta(seconds=self.circuit_reset_seconds)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float | None:
        if response.status_code == 429:
            if self.marketplace.lower() == "wb":
                wb_delay = wb_retry_delay_seconds(response)
                if wb_delay is not None:
                    return wb_delay
            return exponential_jitter_delay_seconds(attempt)
        if 500 <= response.status_code <= 599:
            return exponential_jitter_delay_seconds(attempt)
        return None

    def _retry_reason(self, response: httpx.Response) -> str | None:
        if response.status_code == 429:
            return "throttled"
        if 500 <= response.status_code <= 599:
            return "server_error"
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | list[Any] | None,
    ) -> Any:
        if self._closed:
            raise RuntimeError("http_client_closed")

        sanitized_headers = redact_mapping(headers or {})
        safe_params = params or {}
        last_exception: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            request_id = uuid.uuid4().hex[:12]
            started_at = time.perf_counter()
            try:
                self._check_circuit()
                response = self._client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
                self._logger.info(
                    (
                        "http_request marketplace=%s request_id=%s method=%s path=%s "
                        "status_code=%s latency_ms=%s attempt=%s"
                    ),
                    self.marketplace,
                    request_id,
                    method,
                    path,
                    response.status_code,
                    latency_ms,
                    attempt,
                )

                if 200 <= response.status_code <= 299:
                    self._record_success()
                    return response.json()

                retry_delay = self._retry_delay(response, attempt)
                retry_reason = self._retry_reason(response)
                if retry_delay is not None and attempt < self.max_attempts:
                    self._logger.warning(
                        (
                            "http_retry marketplace=%s request_id=%s method=%s path=%s "
                            "status_code=%s delay_s=%s attempt=%s reason=%s headers=%s params=%s"
                        ),
                        self.marketplace,
                        request_id,
                        method,
                        path,
                        response.status_code,
                        round(retry_delay, 3),
                        attempt,
                        retry_reason,
                        sanitized_headers,
                        safe_params,
                    )
                    sleep_seconds(retry_delay)
                    continue

                failure_reason = retry_reason or "client_error"
                if retry_reason is not None and attempt >= self.max_attempts:
                    failure_reason = f"{retry_reason}_retry_exhausted"
                self._logger.warning(
                    (
                        "http_fail_fast marketplace=%s request_id=%s method=%s path=%s "
                        "status_code=%s latency_ms=%s attempt=%s reason=%s headers=%s params=%s"
                    ),
                    self.marketplace,
                    request_id,
                    method,
                    path,
                    response.status_code,
                    latency_ms,
                    attempt,
                    failure_reason,
                    sanitized_headers,
                    safe_params,
                )
                self._record_failure()
                response.raise_for_status()
            except CircuitOpenError:
                self._logger.warning(
                    (
                        "http_fail_fast marketplace=%s request_id=%s method=%s path=%s "
                        "latency_ms=%s attempt=%s reason=%s headers=%s params=%s"
                    ),
                    self.marketplace,
                    request_id,
                    method,
                    path,
                    round((time.perf_counter() - started_at) * 1000.0, 2),
                    attempt,
                    "circuit_open",
                    sanitized_headers,
                    safe_params,
                )
                raise
            except httpx.RequestError as exc:
                last_exception = exc
                latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
                if attempt < self.max_attempts:
                    retry_delay = exponential_jitter_delay_seconds(attempt)
                    self._logger.warning(
                        (
                            "http_retry marketplace=%s request_id=%s method=%s path=%s "
                            "latency_ms=%s delay_s=%s attempt=%s reason=%s error=%s "
                            "headers=%s params=%s"
                        ),
                        self.marketplace,
                        request_id,
                        method,
                        path,
                        latency_ms,
                        round(retry_delay, 3),
                        attempt,
                        "transport_error",
                        exc.__class__.__name__,
                        sanitized_headers,
                        safe_params,
                    )
                    sleep_seconds(retry_delay)
                    continue
                self._logger.warning(
                    (
                        "http_fail_fast marketplace=%s request_id=%s method=%s path=%s "
                        "latency_ms=%s attempt=%s reason=%s error=%s headers=%s params=%s"
                    ),
                    self.marketplace,
                    request_id,
                    method,
                    path,
                    latency_ms,
                    attempt,
                    "transport_error_retry_exhausted",
                    exc.__class__.__name__,
                    sanitized_headers,
                    safe_params,
                )
                self._record_failure()
                raise
            except ValueError:
                # JSON decode failure should not be retried.
                self._record_failure()
                raise

        if last_exception is not None:
            raise last_exception
        raise RuntimeError("unexpected_http_client_state")
