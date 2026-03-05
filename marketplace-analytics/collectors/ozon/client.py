"""Ozon API client."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

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

    def postings_since(self, from_ts: datetime, to_ts: datetime, limit: int = 1000) -> list[dict[str, Any]]:
        body = {
            "dir": "ASC",
            "filter": {
                "since": from_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": to_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "limit": max(1, min(limit, 1000)),
            "offset": 0,
            "with": {"analytics_data": True, "financial_data": True},
        }
        payload = self.http.post(endpoints.POSTINGS_LIST_PATH, headers=self._headers(), json=body)
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("postings"), list):
                return result["postings"]
        return []

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
