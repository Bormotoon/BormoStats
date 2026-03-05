"""WB API client."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from collectors.common.http_client import JsonHttpClient
from collectors.wb import endpoints


class WbApiClient:
    def __init__(self, statistics_token: str, analytics_token: str) -> None:
        self.statistics_token = statistics_token
        self.analytics_token = analytics_token
        self.statistics = JsonHttpClient(endpoints.STATISTICS_BASE_URL)
        self.analytics = JsonHttpClient(endpoints.ANALYTICS_BASE_URL)

    def _statistics_headers(self) -> dict[str, str]:
        return {"Authorization": self.statistics_token}

    def _analytics_headers(self) -> dict[str, str]:
        return {"Authorization": self.analytics_token}

    def sales_since(self, date_from: datetime) -> list[dict[str, Any]]:
        payload = self.statistics.get(
            endpoints.SALES_PATH,
            headers=self._statistics_headers(),
            params={"dateFrom": date_from.strftime("%Y-%m-%dT%H:%M:%S")},
        )
        return payload if isinstance(payload, list) else []

    def orders_since(self, date_from: datetime) -> list[dict[str, Any]]:
        payload = self.statistics.get(
            endpoints.ORDERS_PATH,
            headers=self._statistics_headers(),
            params={"dateFrom": date_from.strftime("%Y-%m-%dT%H:%M:%S")},
        )
        return payload if isinstance(payload, list) else []

    def stocks(self) -> list[dict[str, Any]]:
        payload = self.statistics.get(
            endpoints.STOCKS_PATH,
            headers=self._statistics_headers(),
        )
        return payload if isinstance(payload, list) else []

    def funnel_daily(self, from_day: date, to_day: date) -> list[dict[str, Any]]:
        body = {
            "period": {
                "begin": from_day.strftime("%Y-%m-%d"),
                "end": to_day.strftime("%Y-%m-%d"),
            },
            "timezone": "Europe/Moscow",
            "aggregationLevel": "day",
        }
        payload = self.analytics.post(
            endpoints.FUNNEL_PATH,
            headers=self._analytics_headers(),
            json=body,
        )
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return data
        if isinstance(payload, list):
            return payload
        return []
