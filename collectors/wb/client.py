"""WB API client."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from collectors.common.http_client import JsonHttpClient
from collectors.wb import endpoints


class WbApiClient:
    def __init__(self, statistics_token: str, analytics_token: str) -> None:
        self.statistics_token = statistics_token
        self.analytics_token = analytics_token
        self.statistics = JsonHttpClient(endpoints.STATISTICS_BASE_URL, marketplace="wb")
        self.analytics = JsonHttpClient(endpoints.ANALYTICS_BASE_URL, marketplace="wb")

    def __enter__(self) -> WbApiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def close(self) -> None:
        self.statistics.close()
        self.analytics.close()

    def _statistics_headers(self) -> dict[str, str]:
        return {"Authorization": self.statistics_token}

    def _analytics_headers(self) -> dict[str, str]:
        return {"Authorization": self.analytics_token}

    def _format_date_from(self, date_from: datetime, flag: int) -> str:
        if flag == 1:
            return date_from.astimezone(UTC).strftime("%Y-%m-%d")
        return date_from.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    def sales_since(self, date_from: datetime, flag: int = 0) -> list[dict[str, Any]]:
        payload = self.statistics.get(
            endpoints.SALES_PATH,
            headers=self._statistics_headers(),
            params={"dateFrom": self._format_date_from(date_from, flag), "flag": flag},
        )
        return payload if isinstance(payload, list) else []

    def sales_for_day(self, day: date) -> list[dict[str, Any]]:
        return self.sales_since(datetime.combine(day, time.min, tzinfo=UTC), flag=1)

    def orders_since(self, date_from: datetime, flag: int = 0) -> list[dict[str, Any]]:
        payload = self.statistics.get(
            endpoints.ORDERS_PATH,
            headers=self._statistics_headers(),
            params={"dateFrom": self._format_date_from(date_from, flag), "flag": flag},
        )
        return payload if isinstance(payload, list) else []

    def orders_for_day(self, day: date) -> list[dict[str, Any]]:
        return self.orders_since(datetime.combine(day, time.min, tzinfo=UTC), flag=1)

    def stocks(self) -> list[dict[str, Any]]:
        """Current stocks on WB warehouses, one record per size and warehouse."""
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.analytics.post(
                endpoints.STOCKS_PATH,
                headers=self._analytics_headers(),
                json={"limit": endpoints.STOCKS_PAGE_LIMIT, "offset": offset},
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                break
            records.extend(item for item in items if isinstance(item, dict))
            if len(items) < endpoints.STOCKS_PAGE_LIMIT:
                break
            offset += endpoints.STOCKS_PAGE_LIMIT
        return records

    def funnel_daily(self, from_day: date, to_day: date) -> list[dict[str, Any]]:
        """Return one v3 product record per card and day in ``[from_day, to_day]``.

        v3 aggregates over the selected period, so each day is requested separately.
        """
        records: list[dict[str, Any]] = []
        day = from_day
        while day <= to_day:
            records.extend(self._funnel_products_for_day(day))
            day += timedelta(days=1)
        return records

    def _funnel_products_for_day(self, day: date) -> list[dict[str, Any]]:
        day_str = day.strftime("%Y-%m-%d")
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.analytics.post(
                endpoints.FUNNEL_PATH,
                headers=self._analytics_headers(),
                json={
                    "selectedPeriod": {"start": day_str, "end": day_str},
                    "limit": endpoints.FUNNEL_PAGE_LIMIT,
                    "offset": offset,
                },
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            products = data.get("products") if isinstance(data, dict) else None
            if not isinstance(products, list):
                break
            currency = data.get("currency") if isinstance(data, dict) else None
            for item in products:
                if isinstance(item, dict):
                    records.append({**item, "currency": currency or "RUB"})
            if len(products) < endpoints.FUNNEL_PAGE_LIMIT:
                break
            offset += endpoints.FUNNEL_PAGE_LIMIT
        return records
