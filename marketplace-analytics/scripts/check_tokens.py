#!/usr/bin/env python3
"""Validate required marketplace credentials and smoke-check API access."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REQUIRED = [
    "WB_TOKEN_STATISTICS",
    "WB_TOKEN_ANALYTICS",
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
    "ADMIN_API_KEY",
]

PLACEHOLDER_VALUES = {"", "...", "change_me"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    warning: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate env + API credentials for WB/Ozon")
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="validate only env values, skip outbound API smoke checks",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=12.0,
        help="HTTP timeout for smoke checks",
    )
    return parser.parse_args()


def _request_json(
    method: str,
    url: str,
    *,
    timeout_seconds: float,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    query = urlencode(params or {})
    target_url = f"{url}?{query}" if query else url
    body_bytes = None
    req_headers = dict(headers or {})
    if json_body is not None:
        req_headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(json_body, ensure_ascii=True).encode("utf-8")

    req = Request(target_url, data=body_bytes, headers=req_headers, method=method.upper())
    with urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310
        status = int(response.status)
        payload = response.read().decode("utf-8", errors="replace")
        if not payload:
            return status, None
        try:
            return status, json.loads(payload)
        except json.JSONDecodeError:
            return status, payload


def _as_error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        body = exc.read().decode("utf-8", errors="replace")[:200]
        return f"http_{exc.code}: {body}"
    if isinstance(exc, URLError):
        return f"network_error: {exc.reason}"
    return str(exc)


def _validate_env() -> list[str]:
    missing: list[str] = []
    for key in REQUIRED:
        value = os.getenv(key, "")
        if value.strip() in PLACEHOLDER_VALUES:
            missing.append(key)
    return missing


def _check_wb_token_ttl() -> CheckResult:
    created_raw = os.getenv("WB_TOKEN_CREATED_AT", "").strip()
    if not created_raw:
        return CheckResult("wb_token_ttl", True, "WB_TOKEN_CREATED_AT not set; ttl reminder disabled", warning=True)

    normalized = created_raw.replace("Z", "+00:00")
    try:
        created_at = datetime.fromisoformat(normalized)
    except ValueError:
        return CheckResult("wb_token_ttl", False, f"invalid WB_TOKEN_CREATED_AT format: {created_raw}")

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)

    expires_at = created_at + timedelta(days=180)
    days_left = (expires_at - datetime.now(UTC)).days

    if days_left < 0:
        return CheckResult("wb_token_ttl", False, f"expired {abs(days_left)}d ago ({expires_at.date().isoformat()})")
    if days_left <= 14:
        return CheckResult("wb_token_ttl", True, f"expires in {days_left}d ({expires_at.date().isoformat()})", warning=True)
    return CheckResult("wb_token_ttl", True, f"days_left={days_left} (expires {expires_at.date().isoformat()})")


def _check_wb_statistics(timeout_seconds: float) -> CheckResult:
    token = os.getenv("WB_TOKEN_STATISTICS", "")
    dt = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        status, payload = _request_json(
            "GET",
            "https://statistics-api.wildberries.ru/api/v1/supplier/sales",
            timeout_seconds=timeout_seconds,
            headers={"Authorization": token},
            params={"dateFrom": dt},
        )
        rows = len(payload) if isinstance(payload, list) else 0
        return CheckResult("wb_statistics", True, f"status={status}, rows={rows}")
    except Exception as exc:
        return CheckResult("wb_statistics", False, _as_error_detail(exc))


def _check_wb_analytics(timeout_seconds: float) -> CheckResult:
    token = os.getenv("WB_TOKEN_ANALYTICS", "")
    today = datetime.now(UTC).date().strftime("%Y-%m-%d")
    body = {
        "period": {"begin": today, "end": today},
        "timezone": "Europe/Moscow",
        "aggregationLevel": "day",
    }
    try:
        status, _ = _request_json(
            "POST",
            "https://seller-analytics-api.wildberries.ru/api/v2/nm-report/detail",
            timeout_seconds=timeout_seconds,
            headers={"Authorization": token},
            json_body=body,
        )
        return CheckResult("wb_analytics", True, f"status={status}")
    except Exception as exc:
        return CheckResult("wb_analytics", False, _as_error_detail(exc))


def _check_ozon_seller(timeout_seconds: float) -> CheckResult:
    client_id = os.getenv("OZON_CLIENT_ID", "")
    api_key = os.getenv("OZON_API_KEY", "")
    now = datetime.now(UTC)
    since = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "dir": "ASC",
        "filter": {"since": since, "to": to},
        "limit": 1,
        "offset": 0,
        "with": {"analytics_data": False, "financial_data": False},
    }
    try:
        status, _ = _request_json(
            "POST",
            "https://api-seller.ozon.ru/v3/posting/fbs/list",
            timeout_seconds=timeout_seconds,
            headers={"Client-Id": client_id, "Api-Key": api_key},
            json_body=body,
        )
        return CheckResult("ozon_seller", True, f"status={status}")
    except Exception as exc:
        return CheckResult("ozon_seller", False, _as_error_detail(exc))


def _check_ozon_perf(timeout_seconds: float) -> CheckResult:
    client_id = os.getenv("OZON_CLIENT_ID", "")
    perf_api_key = os.getenv("OZON_PERF_API_KEY", "")
    if not perf_api_key.strip():
        return CheckResult("ozon_perf", True, "not configured; skipped", warning=True)

    day = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    body = {"date_from": day, "date_to": day, "group_by": "DATE"}
    try:
        status, _ = _request_json(
            "POST",
            "https://api-seller.ozon.ru/v1/advertising/statistics",
            timeout_seconds=timeout_seconds,
            headers={"Client-Id": client_id, "Api-Key": perf_api_key},
            json_body=body,
        )
        return CheckResult("ozon_perf", True, f"status={status}")
    except Exception as exc:
        return CheckResult("ozon_perf", False, _as_error_detail(exc), warning=True)


def main() -> int:
    args = parse_args()

    missing = _validate_env()
    if missing:
        print("Missing or placeholder values:")
        for key in missing:
            print(f"- {key}")
        return 1

    print("Environment values look configured.")
    if args.skip_api:
        print("Skipping API smoke checks (--skip-api).")
        return 0

    results = [
        _check_wb_token_ttl(),
        _check_wb_statistics(args.timeout_seconds),
        _check_wb_analytics(args.timeout_seconds),
        _check_ozon_seller(args.timeout_seconds),
        _check_ozon_perf(args.timeout_seconds),
    ]

    failed_hard = False
    for result in results:
        if result.ok and result.warning:
            print(f"[WARN] {result.name}: {result.detail}")
            continue
        if result.ok:
            print(f"[OK] {result.name}: {result.detail}")
            continue
        level = "WARN" if result.warning else "FAIL"
        print(f"[{level}] {result.name}: {result.detail}")
        if not result.warning:
            failed_hard = True

    return 1 if failed_hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
