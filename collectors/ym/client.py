"""Yandex Market Partner API client with cursor paging and report polling."""

from __future__ import annotations

import csv
import io
import json
import time
import zipfile
from contextlib import suppress
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from collectors.common.http_client import JsonHttpClient
from collectors.ym import endpoints
from collectors.ym.errors import YmApiError, YmAuthError, YmRateLimitError


def _items(payload: Any, *keys: str) -> list[dict[str, Any]]:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return [row for row in current if isinstance(row, dict)] if isinstance(current, list) else []


class YmClient:
    def __init__(self, api_key: str, *, report_poll_seconds: float = 5.0) -> None:
        self.api_key = api_key
        self.report_poll_seconds = max(0.1, report_poll_seconds)
        self.http = JsonHttpClient(endpoints.BASE_URL, marketplace="ym")

    def __enter__(self) -> YmClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def close(self) -> None:
        self.http.close()

    def _headers(self) -> dict[str, str]:
        return {"Api-Key": self.api_key, "Content-Type": "application/json"}

    def _post(
        self, path: str, body: dict[str, Any], *, params: dict[str, Any] | None = None
    ) -> Any:
        try:
            payload = self.http.post(path, headers=self._headers(), json=body, params=params)
            if isinstance(payload, dict) and payload.get("status") == "ERROR":
                raise YmApiError(f"Yandex Market {path} returned an API error")
            return payload
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 420:
                raise YmRateLimitError("Yandex Market API rate limit exceeded (HTTP 420)") from exc
            if status in {401, 403}:
                raise YmAuthError("Yandex Market API credentials rejected") from exc
            raise

    def campaigns(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        token = ""
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"limit": 100}
            if token:
                params["pageToken"] = token
            try:
                payload = self.http.get(
                    endpoints.CAMPAIGNS_PATH, headers=self._headers(), params=params
                )
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in {401, 403}:
                    raise YmAuthError("Yandex Market API credentials rejected") from exc
                if status == 420:
                    raise YmRateLimitError(
                        "Yandex Market API rate limit exceeded (HTTP 420)"
                    ) from exc
                raise
            result = payload.get("result", payload) if isinstance(payload, dict) else {}
            rows.extend(_items(result, "campaigns"))
            paging = result.get("paging", {}) if isinstance(result, dict) else {}
            token = str(paging.get("nextPageToken") or "") if isinstance(paging, dict) else ""
            if not token:
                return rows
            if token in seen:
                raise RuntimeError("Yandex Market campaigns returned the same page token twice")
            seen.add(token)

    def offer_mappings(self, business_id: str, *, page_size: int = 200) -> list[dict[str, Any]]:
        return self._paged(
            endpoints.OFFER_MAPPINGS_PATH.format(business_id=business_id), {}, min(page_size, 100)
        )

    def campaign_offers(self, campaign_id: str, *, page_size: int = 200) -> list[dict[str, Any]]:
        return self._paged(
            endpoints.CAMPAIGN_OFFERS_PATH.format(campaign_id=campaign_id), {}, page_size
        )

    def orders(
        self,
        business_id: str,
        date_from: date,
        date_to: date,
        *,
        page_size: int = 200,
        updated: bool = False,
        campaign_id: str = "",
    ) -> list[dict[str, Any]]:
        if date_to < date_from:
            raise ValueError("date_to must not precede date_from")
        rows: list[dict[str, Any]] = []
        window_start = date_from
        while window_start <= date_to:
            window_end = min(window_start + timedelta(days=29), date_to)
            rows.extend(
                self._paged(
                    endpoints.ORDERS_PATH.format(business_id=business_id),
                    {
                        **({"campaignIds": [int(campaign_id)]} if campaign_id else {}),
                        "dates": {
                            ("updateDateFrom" if updated else "creationDateFrom"): (
                                window_start.isoformat() + "T00:00:00Z"
                            )
                            if updated
                            else window_start.isoformat(),
                            ("updateDateTo" if updated else "creationDateTo"): (
                                window_end + timedelta(days=1)
                            ).isoformat()
                            + ("T00:00:00Z" if updated else ""),
                        },
                    },
                    min(page_size, 50),
                )
            )
            window_start = window_end + timedelta(days=1)
        return rows

    def stats_orders(
        self, campaign_id: str, date_from: datetime, date_to: datetime, *, page_size: int = 200
    ) -> list[dict[str, Any]]:
        return self._paged(
            endpoints.STATS_ORDERS_PATH.format(campaign_id=campaign_id),
            {"updateFrom": date_from.date().isoformat(), "updateTo": date_to.date().isoformat()},
            page_size,
        )

    def stocks(self, campaign_id: str, *, page_size: int = 200) -> list[dict[str, Any]]:
        return self._paged(
            endpoints.STOCKS_PATH.format(campaign_id=campaign_id), {}, min(page_size, 100)
        )

    def partner_stocks(self, business_id: str, campaign_id: str) -> list[dict[str, Any]]:
        warehouses = self._paged(f"/v3/businesses/{business_id}/warehouses", {}, 30)
        result: list[dict[str, Any]] = []
        for warehouse in warehouses:
            models = warehouse.get("models") or []
            if any(isinstance(model, dict) and not model.get("campaignId") for model in models):
                raise ValueError("Yandex warehouse has no unambiguous campaignId")
            if not any(
                str(model.get("campaignId") or "") == campaign_id
                for model in models
                if isinstance(model, dict)
            ):
                continue
            warehouse_id = warehouse.get("id")
            if not warehouse_id:
                continue
            offers = self._paged(
                f"/v3/businesses/{business_id}/offers/stocks",
                {"partnerWarehouseId": warehouse_id},
                100,
            )
            result.append(
                {
                    "warehouseId": warehouse_id,
                    "warehouseName": warehouse.get("name", ""),
                    "offers": offers,
                }
            )
        return result

    def offer_prices(self, campaign_id: str, *, page_size: int = 200) -> list[dict[str, Any]]:
        return self._paged(
            endpoints.OFFER_PRICES_PATH.format(campaign_id=campaign_id), {}, page_size
        )

    def calculate_tariffs(
        self, campaign_id: str, offers: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not offers:
            return []
        if len(offers) > 200:
            raise ValueError("Yandex tariff request supports at most 200 offers")
        payload = self._post(
            endpoints.TARIFFS_CALCULATE_PATH,
            {"parameters": {"campaignId": int(campaign_id)}, "offers": offers},
        )
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        rows = _items(result, "offers")
        if len(rows) != len(offers):
            raise ValueError("Yandex tariff result does not match requested offers")
        return rows

    def feedbacks(
        self, business_id: str, body: dict[str, Any], *, page_size: int = 200
    ) -> list[dict[str, Any]]:
        return self._paged(
            endpoints.FEEDBACKS_PATH.format(business_id=business_id), body, min(page_size, 50)
        )

    def _paged(self, path: str, body: dict[str, Any], page_size: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        token = ""
        seen_tokens: set[str] = set()
        limit = min(max(1, page_size), endpoints.MAX_PAGE_SIZE)
        while True:
            params: dict[str, Any] = {"limit": limit}
            if token:
                params["pageToken"] = token
            payload = self._post(path, body, params=params)
            result = payload.get("result", payload) if isinstance(payload, dict) else {}
            rows = next(
                (
                    _items(result, key)
                    for key in (
                        "orders",
                        "bids",
                        "offerMappings",
                        "offers",
                        "stocks",
                        "warehouses",
                        "goodsFeedbacks",
                        "prices",
                        "feedbacks",
                        "items",
                    )
                    if isinstance(result, dict) and isinstance(result.get(key), list)
                ),
                [],
            )
            collected.extend(rows)
            paging = result.get("paging", {}) if isinstance(result, dict) else {}
            next_token = str(
                (paging.get("nextPageToken") if isinstance(paging, dict) else "")
                or (result.get("nextPageToken") if isinstance(result, dict) else "")
                or ""
            )
            if not rows or not next_token:
                return collected
            if next_token in seen_tokens:
                raise RuntimeError(f"Yandex Market {path} returned the same page token twice")
            seen_tokens.add(next_token)
            token = next_token

    def generate_and_fetch_report(
        self,
        report_type: str,
        body: dict[str, Any],
        *,
        timeout_seconds: float = 900,
        output_format: str = "CSV",
    ) -> list[dict[str, Any]]:
        payload = self._post(
            endpoints.REPORT_GENERATE_PATH.format(report_type=report_type),
            body,
            params={"format": output_format.upper()},
        )
        result = payload.get("result", payload) if isinstance(payload, dict) else {}
        report_id = str(result.get("reportId") or result.get("id") or "")
        if not report_id:
            raise RuntimeError(f"Yandex Market {report_type} report response has no report id")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            info = self.http.get(
                endpoints.REPORT_INFO_PATH.format(report_id=report_id), headers=self._headers()
            )
            report = info.get("result", info) if isinstance(info, dict) else {}
            status = str(report.get("status") or "").upper()
            if status in {"FAILED", "ERROR"}:
                raise RuntimeError(f"Yandex Market report {report_id} failed: {report}")
            if status == "DONE":
                url = str(report.get("file") or report.get("url") or "")
                if not url:
                    return _items(report, "rows")
                return self._download_report(url, output_format, report_type=report_type)
            time.sleep(self.report_poll_seconds)
        raise TimeoutError(f"Yandex Market report {report_id} did not finish before timeout")

    def _download_report(
        self, url: str, output_format: str, *, report_type: str = ""
    ) -> list[dict[str, Any]]:
        response = httpx.get(url, timeout=120)
        response.raise_for_status()
        content = response.content
        files: list[bytes] = [content]
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                sheet = {
                    "united-netting": "transaction_date",
                    "shows-sales": "sales_funnel_report",
                    "shows-boost": "business_shows_boost_consolidated_campaigns",
                }.get(report_type)
                files = [
                    archive.read(name)
                    for name in archive.namelist()
                    if name.lower().endswith((".csv", ".json")) and (not sheet or sheet in name)
                ]
                if not files:
                    raise ValueError("Yandex report archive contains no CSV/JSON files")
        rows: list[dict[str, Any]] = []
        for data in files:
            text = data.decode("utf-8-sig")
            if output_format.upper() == "JSON":
                parsed = json.loads(text)
                rows.extend(parsed if isinstance(parsed, list) else _items(parsed, "rows"))
            else:
                try:
                    dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                rows.extend(csv.DictReader(io.StringIO(text), dialect=dialect))
        return rows
