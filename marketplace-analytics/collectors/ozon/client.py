"""Ozon API client."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from collectors.common.http_client import JsonHttpClient
from collectors.ozon import endpoints


class OzonApiClient:
    def __init__(self, client_id: str, api_key: str, perf_api_key: str = "") -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.perf_api_key = perf_api_key or api_key
        self.http = JsonHttpClient(endpoints.BASE_URL, marketplace="ozon")

    def _headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _perf_headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.perf_api_key,
            "Content-Type": "application/json",
        }

    def _extract_postings_result(self, payload: Any) -> tuple[list[dict[str, Any]], bool | None]:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                postings = result.get("postings")
                has_next = result.get("has_next")
                if isinstance(postings, list):
                    return [item for item in postings if isinstance(item, dict)], bool(has_next)
                items = result.get("items")
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)], bool(has_next)
            if isinstance(result, list):
                return [item for item in result if isinstance(item, dict)], None
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], None
        return [], None

    def _postings_since_path(
        self,
        *,
        path: str,
        from_ts: datetime,
        to_ts: datetime,
        limit: int,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        collected: list[dict[str, Any]] = []
        offset = 0
        while True:
            body = {
                "dir": "ASC",
                "filter": {
                    "since": from_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": to_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "limit": safe_limit,
                "offset": offset,
                "with": {"analytics_data": True, "financial_data": True},
            }
            payload = self.http.post(path, headers=headers, json=body)
            postings, has_next = self._extract_postings_result(payload)
            if not postings:
                break
            collected.extend(postings)

            if has_next is False:
                break
            if len(postings) < safe_limit:
                break
            offset += safe_limit

        return collected

    def postings_since(
        self,
        from_ts: datetime,
        to_ts: datetime,
        limit: int = 1000,
        schemas: tuple[str, ...] = ("fbs",),
    ) -> list[dict[str, Any]]:
        unique_by_posting: dict[str, dict[str, Any]] = {}
        fallback_items: list[dict[str, Any]] = []

        for schema in schemas:
            normalized = schema.strip().lower()
            if normalized not in {"fbs", "fbo"}:
                continue

            path = (
                endpoints.POSTINGS_FBO_LIST_PATH
                if normalized == "fbo"
                else endpoints.POSTINGS_FBS_LIST_PATH
            )
            try:
                postings = self._postings_since_path(
                    path=path,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    limit=limit,
                    headers=self._headers(),
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if normalized == "fbo" and status in {403, 404, 405}:
                    continue
                raise

            for posting in postings:
                posting_number = str(
                    posting.get("posting_number")
                    or posting.get("postingNumber")
                    or posting.get("order_id")
                    or ""
                )
                if posting_number:
                    unique_by_posting[posting_number] = posting
                    continue
                fallback_items.append(posting)

        return list(unique_by_posting.values()) + fallback_items

    def postings_since_fbs(self, from_ts: datetime, to_ts: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        return self.postings_since(from_ts=from_ts, to_ts=to_ts, limit=limit, schemas=("fbs",))

    def postings_since_fbo(self, from_ts: datetime, to_ts: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        return self.postings_since(from_ts=from_ts, to_ts=to_ts, limit=limit, schemas=("fbo",))

    def postings_since_all(self, from_ts: datetime, to_ts: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        return self.postings_since(from_ts=from_ts, to_ts=to_ts, limit=limit, schemas=("fbs", "fbo"))

    def stocks(self, limit: int = 1000) -> list[dict[str, Any]]:
        body = {"limit": max(1, min(limit, 1000)), "offset": 0}
        payload = self.http.post(endpoints.STOCKS_PATH, headers=self._headers(), json=body)
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("items"), list):
                return result["items"]
            if isinstance(result, list):
                return result
        if isinstance(payload, list):
            return payload
        return []

    def finance_operations(
        self,
        from_ts: datetime,
        to_ts: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        page = 1
        collected: list[dict[str, Any]] = []

        while True:
            body = {
                "filter": {
                    "date": {
                        "from": from_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": to_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                },
                "page": page,
                "page_size": safe_limit,
            }
            payload = self.http.post(endpoints.FINANCE_OPS_PATH, headers=self._headers(), json=body)
            operations = self._extract_finance_operations(payload)
            if not operations:
                break
            collected.extend(operations)
            if len(operations) < safe_limit:
                break
            page += 1

        return collected

    def _extract_finance_operations(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                operations = result.get("operations")
                if isinstance(operations, list):
                    return [item for item in operations if isinstance(item, dict)]
                items = result.get("items")
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
            if isinstance(result, list):
                return [item for item in result if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def ads_daily(self, for_day: date) -> list[dict[str, Any]]:
        body = {
            "date_from": for_day.strftime("%Y-%m-%d"),
            "date_to": for_day.strftime("%Y-%m-%d"),
            "group_by": "DATE",
        }
        payload = self.http.post(endpoints.ADS_STATS_PATH, headers=self._perf_headers(), json=body)
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, list):
                return result
        if isinstance(payload, list):
            return payload
        return []
