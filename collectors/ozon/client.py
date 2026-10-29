"""Ozon API clients: Seller API and Performance API (ads)."""

from __future__ import annotations

import time
from contextlib import suppress
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from collectors.common.http_client import JsonHttpClient
from collectors.ozon import endpoints


class _BuyoutHttpClient(JsonHttpClient):
    def _retry_delay(self, response: httpx.Response, attempt: int) -> float | None:
        if response.status_code == 429:
            try:
                return max(5.0, min(60.0, float(response.headers.get('Retry-After', '60'))))
            except ValueError:
                return 60.0
        return super()._retry_delay(response, attempt)


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _ozon_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class OzonApiClient:
    def __init__(self, client_id: str, api_key: str) -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.http = JsonHttpClient(endpoints.BASE_URL, marketplace="ozon")

    def __enter__(self) -> OzonApiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def close(self) -> None:
        self.http.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    # -- Postings --

    def _postings_window(
        self,
        *,
        path: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        cursor = ""
        while True:
            body: dict[str, Any] = {
                "filter": {"since": _ozon_ts(from_ts), "to": _ozon_ts(to_ts)},
                "limit": endpoints.POSTINGS_PAGE_LIMIT,
                "sort_dir": "ASC",
                "with": {"analytics_data": True, "financial_data": True},
            }
            if cursor:
                body["cursor"] = cursor
            payload = self.http.post(path, headers=self._headers(), json=body)
            if not isinstance(payload, dict):
                break
            postings = _dict_items(payload.get("postings"))
            collected.extend(postings)

            next_cursor = str(payload.get("cursor") or "")
            if not postings or not payload.get("has_next") or not next_cursor:
                break
            if next_cursor == cursor:
                raise RuntimeError(f"ozon {path} returned the same cursor twice")
            cursor = next_cursor
        return collected

    def _postings_since_path(
        self,
        *,
        path: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        window = timedelta(days=endpoints.POSTINGS_MAX_WINDOW_DAYS)
        window_start = from_ts
        while window_start < to_ts:
            window_end = min(window_start + window, to_ts)
            collected.extend(
                self._postings_window(path=path, from_ts=window_start, to_ts=window_end)
            )
            window_start = window_end
        return collected

    def postings_since(
        self,
        from_ts: datetime,
        to_ts: datetime,
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
                postings = self._postings_since_path(path=path, from_ts=from_ts, to_ts=to_ts)
            except httpx.HTTPStatusError as exc:
                # sellers without an FBO contract are refused, FBS must still be collected
                if normalized == "fbo" and exc.response.status_code == 403:
                    continue
                raise

            for posting in postings:
                posting_number = str(posting.get("posting_number") or "")
                if posting_number:
                    unique_by_posting[posting_number] = posting
                    continue
                fallback_items.append(posting)

        return list(unique_by_posting.values()) + fallback_items

    # -- Stocks --

    def stocks(self) -> list[dict[str, Any]]:
        """FBS, rFBS and FBP stocks from ``/v4/product/info/stocks``."""
        collected: list[dict[str, Any]] = []
        cursor = ""
        while True:
            body: dict[str, Any] = {
                "filter": {"visibility": "ALL"},
                "limit": endpoints.STOCKS_PAGE_LIMIT,
            }
            if cursor:
                body["cursor"] = cursor
            payload = self.http.post(endpoints.STOCKS_PATH, headers=self._headers(), json=body)
            if not isinstance(payload, dict):
                break
            items = _dict_items(payload.get("items"))
            collected.extend(items)

            next_cursor = str(payload.get("cursor") or "")
            total = payload.get("total")
            if not items or not next_cursor or next_cursor == cursor:
                break
            if isinstance(total, int) and len(collected) >= total:
                break
            cursor = next_cursor
        return collected

    def fbo_stocks(self, skus: list[int]) -> list[dict[str, Any]]:
        """FBO stocks per Ozon warehouse from ``/v1/analytics/stocks``."""
        unique = list(dict.fromkeys(sku for sku in skus if sku))
        collected: list[dict[str, Any]] = []
        batch = endpoints.FBO_STOCKS_SKU_BATCH
        for start in range(0, len(unique), batch):
            if start:
                time.sleep(endpoints.FBO_STOCKS_BATCH_PAUSE_SECONDS)
            body = {"skus": [str(sku) for sku in unique[start : start + batch]]}
            try:
                payload = self.http.post(
                    endpoints.FBO_STOCKS_PATH, headers=self._headers(), json=body
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    raise
                time.sleep(endpoints.FBO_STOCKS_RATE_WINDOW_SECONDS)
                payload = self.http.post(
                    endpoints.FBO_STOCKS_PATH, headers=self._headers(), json=body
                )
            if isinstance(payload, dict):
                collected.extend(_dict_items(payload.get("items")))
        return collected

    # -- Catalogue --

    def product_ids(self) -> list[int]:
        """Ids of every product of the seller (all visibilities), via ``last_id`` paging."""
        ids: list[int] = []
        last_id = ""
        for _ in range(endpoints.PRODUCT_MAX_PAGES):
            payload = self.http.post(
                endpoints.PRODUCT_LIST_PATH,
                headers=self._headers(),
                json={
                    "filter": {"visibility": "ALL"},
                    "last_id": last_id,
                    "limit": endpoints.PRODUCT_LIST_PAGE_LIMIT,
                },
            )
            result = payload.get("result") if isinstance(payload, dict) else None
            items = _dict_items(result.get("items")) if isinstance(result, dict) else []
            for item in items:
                with suppress(KeyError, TypeError, ValueError):
                    ids.append(int(item["product_id"]))
            next_id = str(result.get("last_id") or "") if isinstance(result, dict) else ""
            if not items or not next_id:
                return ids
            if next_id == last_id:
                raise RuntimeError("ozon product list returned the same last_id twice")
            last_id = next_id
        raise RuntimeError(f"ozon product list exceeded {endpoints.PRODUCT_MAX_PAGES} pages")

    def product_info(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Card data (name, prices, images, statuses, commissions, ...) per product."""
        collected: list[dict[str, Any]] = []
        batch = endpoints.PRODUCT_BATCH
        for start in range(0, len(product_ids), batch):
            payload = self.http.post(
                endpoints.PRODUCT_INFO_LIST_PATH,
                headers=self._headers(),
                json={"product_id": [str(pid) for pid in product_ids[start : start + batch]]},
            )
            if isinstance(payload, dict):
                collected.extend(_dict_items(payload.get("items")))
        return collected

    def product_attributes(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Characteristics, complex attributes and images per product."""
        collected: list[dict[str, Any]] = []
        batch = endpoints.PRODUCT_BATCH
        for start in range(0, len(product_ids), batch):
            ids = [str(pid) for pid in product_ids[start : start + batch]]
            last_id = ""
            for _ in range(endpoints.PRODUCT_MAX_PAGES):
                payload = self.http.post(
                    endpoints.PRODUCT_ATTRIBUTES_PATH,
                    headers=self._headers(),
                    json={
                        "filter": {"product_id": ids, "visibility": "ALL"},
                        "limit": batch,
                        "last_id": last_id,
                        "sort_dir": "ASC",
                    },
                )
                if not isinstance(payload, dict):
                    break
                items = _dict_items(payload.get("result"))
                collected.extend(items)
                next_id = str(payload.get("last_id") or "")
                if not items or not next_id or next_id == last_id:
                    break
                last_id = next_id
        return collected

    def product_prices(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Price, marketing price, commissions and price indexes per product."""
        collected: list[dict[str, Any]] = []
        batch = endpoints.PRODUCT_BATCH
        for start in range(0, len(product_ids), batch):
            ids = [str(pid) for pid in product_ids[start : start + batch]]
            cursor = ""
            for _ in range(endpoints.PRODUCT_MAX_PAGES):
                payload = self.http.post(
                    endpoints.PRODUCT_PRICES_PATH,
                    headers=self._headers(),
                    json={
                        "filter": {"product_id": ids, "visibility": "ALL"},
                        "limit": batch,
                        "cursor": cursor,
                    },
                )
                if not isinstance(payload, dict):
                    break
                items = _dict_items(payload.get("items"))
                collected.extend(items)
                next_cursor = str(payload.get("cursor") or "")
                if not items or not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
        return collected

    # -- Finance --

    def finance_buyouts(self, from_day: date, to_day: date) -> dict[str, Any]:
        if not 0 <= (to_day-from_day).days < 31:
            raise ValueError('Buyout report requires a period of at most 31 days')
        # This report has a much stricter quota than ordinary finance methods.
        with _BuyoutHttpClient(endpoints.BASE_URL, marketplace='ozon', max_attempts=12) as http:
            payload=http.post('/v1/finance/products/buyout',headers=self._headers(),
                              json={'date_from':from_day.isoformat(),'date_to':to_day.isoformat()})
        if not isinstance(payload,dict) or not isinstance(payload.get('products'),list):
            raise ValueError('Buyout report is unavailable')
        return payload

    def finance_realization(self, year: int, month: int) -> dict[str, Any]:
        """Monthly closed realization report (one response, no pagination)."""
        payload = self.http.post(
            endpoints.FINANCE_REALIZATION_PATH,
            headers=self._headers(), json={"year": year, "month": month},
        )
        if not isinstance(payload, dict):
            raise ValueError("Invalid realization response")
        return payload

    def finance_accrual_types(self) -> dict[int, str]:
        """Accrual type dictionary ``{type_id: name}``."""
        payload = self.http.post(
            endpoints.FINANCE_ACCRUAL_TYPES_PATH, headers=self._headers(), json={}
        )
        types: dict[int, str] = {}
        if isinstance(payload, dict):
            for item in _dict_items(payload.get("accrual_types")):
                with suppress(KeyError, TypeError, ValueError):
                    types[int(item["id"])] = str(item.get("name") or item.get("description") or "")
        return types

    def finance_balance(self, date_from: date, date_to: date) -> dict[str, Any]:
        """Balance movement over ``[date_from, date_to]`` (one day per call for daily rows)."""
        payload = self.http.post(
            endpoints.FINANCE_BALANCE_PATH,
            headers=self._headers(),
            json={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        )
        return payload if isinstance(payload, dict) else {}

    def finance_accruals_for_day(self, day: date) -> list[dict[str, Any]]:
        """All accruals for one calendar day, following ``last_id`` pagination."""
        collected: list[dict[str, Any]] = []
        last_id = ""
        seen: set[str] = set()
        for _ in range(endpoints.FINANCE_ACCRUAL_MAX_PAGES_PER_DAY):
            # the method accepts exactly one date; last_id is only valid with the same date
            body = {"date": day.isoformat(), "last_id": last_id}
            payload = self.http.post(
                endpoints.FINANCE_ACCRUAL_BY_DAY_PATH, headers=self._headers(), json=body
            )
            if not isinstance(payload, dict):
                break
            accruals = _dict_items(payload.get("accruals"))
            collected.extend(accruals)

            next_id = str(payload.get("last_id") or "")
            if not accruals or not next_id:
                return collected
            if next_id in seen:
                raise RuntimeError(f"ozon accruals for {day} returned last_id {next_id} twice")
            seen.add(next_id)
            last_id = next_id
        else:
            raise RuntimeError(
                f"ozon accruals for {day} exceeded "
                f"{endpoints.FINANCE_ACCRUAL_MAX_PAGES_PER_DAY} pages"
            )
        return collected


class OzonPerformanceClient:
    """Ozon Performance API (ads) with OAuth client-credentials tokens."""

    # refresh a little before Ozon expires the token (30 min lifetime)
    _TOKEN_EXPIRY_SKEW_SECONDS = 60

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = JsonHttpClient(endpoints.PERFORMANCE_BASE_URL, marketplace="ozon_performance")
        self._token = ""
        self._token_expires_at = 0.0

    def __enter__(self) -> OzonPerformanceClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def close(self) -> None:
        self.http.close()

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        payload = self.http.post(
            endpoints.PERFORMANCE_TOKEN_PATH,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        token = str(payload.get("access_token") or "") if isinstance(payload, dict) else ""
        if not token:
            raise RuntimeError("ozon performance token response has no access_token")
        try:
            expires_in = float(payload.get("expires_in") or 0)
        except TypeError, ValueError:
            expires_in = 0.0
        self._token = token
        self._token_expires_at = time.monotonic() + max(
            0.0, expires_in - self._TOKEN_EXPIRY_SKEW_SECONDS
        )
        return token

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        for attempt in range(2):
            headers = {
                "Authorization": f"Bearer {self._access_token()}",
                "Accept": "application/json",
            }
            try:
                return self.http.get(path, headers=headers, params=params)
            except httpx.HTTPStatusError as exc:
                # a token revoked before its expiry is refreshed once
                if exc.response.status_code == 401 and attempt == 0:
                    self._token = ""
                    continue
                raise
        return None

    def daily_stats(self, from_day: date, to_day: date) -> list[dict[str, Any]]:
        """Per-campaign daily stats; without ``campaignIds`` Ozon returns every campaign."""
        payload = self._get(
            endpoints.PERFORMANCE_DAILY_STATS_PATH,
            {"dateFrom": from_day.isoformat(), "dateTo": to_day.isoformat()},
        )
        if isinstance(payload, dict):
            return _dict_items(payload.get("rows"))
        return _dict_items(payload)

    def campaigns(self) -> list[dict[str, Any]]:
        """Campaign type, placement and bid strategy from Performance metadata."""
        payload = self._get(endpoints.PERFORMANCE_CAMPAIGNS_PATH, {})
        if not isinstance(payload, dict) or not isinstance(payload.get('list'), list):
            raise ValueError('Performance campaign metadata response has no list')
        records = _dict_items(payload['list'])
        if int(payload.get('total', len(records))) > len(records):
            raise ValueError('Performance returned an incomplete campaign list')
        return records
