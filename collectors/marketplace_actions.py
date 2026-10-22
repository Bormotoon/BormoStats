"""Clients for marketplace write operations: prices, ad bids and stocks.

They reuse :class:`JsonHttpClient`, so every call gets retries with backoff on
429/5xx (honouring WB rate-limit headers) and a per-client circuit breaker.
Callers are responsible for dry-run, idempotency and the audit trail
(see ``workers/app/utils/marketplace_actions.py``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from collectors.common.http_client import CircuitOpenError, JsonHttpClient
from collectors.ozon import endpoints as ozon_endpoints
from collectors.wb import endpoints as wb_endpoints

OZON_STOCKS_BATCH = 100
WB_BIDS_BATCH = 50
_BODY_LIMIT = 2000


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    status_code: int
    body: str

    @classmethod
    def success(cls, payload: Any, status_code: int = 200) -> ActionResult:
        text = "" if payload is None else json.dumps(payload, ensure_ascii=False)[:_BODY_LIMIT]
        return cls(ok=True, status_code=status_code, body=text)

    @classmethod
    def failure(cls, exc: Exception) -> ActionResult:
        if isinstance(exc, httpx.HTTPStatusError):
            return cls(
                ok=False,
                status_code=exc.response.status_code,
                body=exc.response.text[:_BODY_LIMIT],
            )
        if isinstance(exc, CircuitOpenError):
            return cls(ok=False, status_code=0, body=f"circuit_open: {exc}"[:_BODY_LIMIT])
        return cls(ok=False, status_code=0, body=f"{type(exc).__name__}: {exc}"[:_BODY_LIMIT])


def _chunks[T](items: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class WbActionsClient:
    """WB write APIs. Each API needs a token of the matching category."""

    def __init__(
        self,
        *,
        prices_token: str = "",
        promotion_token: str = "",
        marketplace_token: str = "",
    ) -> None:
        self._prices_token = prices_token
        self._promotion_token = promotion_token
        self._marketplace_token = marketplace_token
        self._prices = JsonHttpClient(wb_endpoints.PRICES_BASE_URL, marketplace="wb")
        self._advert = JsonHttpClient(wb_endpoints.ADVERT_BASE_URL, marketplace="wb")
        self._marketplace = JsonHttpClient(wb_endpoints.MARKETPLACE_BASE_URL, marketplace="wb")

    def close(self) -> None:
        self._prices.close()
        self._advert.close()
        self._marketplace.close()

    def __enter__(self) -> WbActionsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def can_set_prices(self) -> bool:
        return bool(self._prices_token)

    @property
    def can_set_bids(self) -> bool:
        return bool(self._promotion_token)

    @property
    def can_set_stocks(self) -> bool:
        return bool(self._marketplace_token)

    def set_price(self, nm_id: int, price: int, discount: int | None = None) -> ActionResult:
        """``price`` is the list price before the seller's discount, ``discount`` its percent.

        The discount is sent whenever it is known, so the card keeps the discount it had
        instead of relying on what WB does with a missing field.
        """
        item: dict[str, int] = {"nmID": nm_id, "price": price}
        if discount is not None:
            item["discount"] = discount
        try:
            payload = self._prices.post(
                wb_endpoints.PRICES_UPLOAD_PATH,
                headers={"Authorization": self._prices_token},
                json={"data": [item]},
            )
        except Exception as exc:
            return ActionResult.failure(exc)
        return ActionResult.success(payload)

    def set_bid(self, advert_id: int, nm_id: int, bid_kopecks: int, placement: str) -> ActionResult:
        body = {
            "bids": [
                {
                    "advert_id": advert_id,
                    "nm_bids": [
                        {"nm_id": nm_id, "bid_kopecks": bid_kopecks, "placement": placement}
                    ],
                }
            ]
        }
        try:
            payload = self._advert.patch(
                wb_endpoints.BIDS_PATH,
                headers={"Authorization": self._promotion_token},
                json=body,
            )
        except Exception as exc:
            return ActionResult.failure(exc)
        return ActionResult.success(payload)

    def set_stocks(self, warehouse_id: int, amounts: Sequence[tuple[int, int]]) -> ActionResult:
        """``amounts`` are ``(chrtId, amount)`` pairs for one warehouse."""
        try:
            self._marketplace.put(
                wb_endpoints.STOCKS_WRITE_PATH.format(warehouse_id=warehouse_id),
                headers={"Authorization": self._marketplace_token},
                json={"stocks": [{"chrtId": chrt, "amount": amount} for chrt, amount in amounts]},
            )
        except Exception as exc:
            return ActionResult.failure(exc)
        return ActionResult.success(None, status_code=204)


class OzonActionsClient:
    def __init__(self, *, client_id: str = "", api_key: str = "") -> None:
        self._client_id = client_id
        self._api_key = api_key
        self._http = JsonHttpClient(ozon_endpoints.BASE_URL, marketplace="ozon")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OzonActionsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._api_key)

    def _headers(self) -> dict[str, str]:
        return {"Client-Id": self._client_id, "Api-Key": self._api_key}

    def set_price(
        self, offer_id: str, price: float, old_price: float = 0.0, min_price: float = 0.0
    ) -> ActionResult:
        """``price`` is the seller's price; ``old_price`` the crossed-out one.

        Ozon reads ``old_price`` "0" as "no discount" and drops the crossed-out price, so the
        caller passes the current one (scaled to the new price) to keep the discount shown.
        ``min_price`` is the card's "предельная цена" (limit price), one for prices and Ozon
        promotions since October 2026: the card takes part in a promotion only while it is not
        above the promotion's price for taking part. Left out when 0.
        """
        item = {
            "offer_id": offer_id,
            "price": f"{price:.2f}",
            "old_price": f"{old_price:.2f}" if old_price > price else "0",
            "currency_code": "RUB",
        }
        if min_price > 0:
            item["min_price"] = f"{min_price:.2f}"
        body = {"prices": [item]}
        try:
            payload = self._http.post(
                ozon_endpoints.PRICES_IMPORT_PATH, headers=self._headers(), json=body
            )
        except Exception as exc:
            return ActionResult.failure(exc)
        return _ozon_result(payload)

    def set_stocks(self, stocks: Sequence[tuple[str, int, int]]) -> ActionResult:
        """``stocks`` are ``(offer_id, stock, warehouse_id)``; sent in batches of 100."""
        responses: list[Any] = []
        for batch in _chunks(list(stocks), OZON_STOCKS_BATCH):
            body = {
                "stocks": [
                    {"offer_id": offer, "stock": stock, "warehouse_id": warehouse}
                    for offer, stock, warehouse in batch
                ]
            }
            try:
                payload = self._http.post(
                    ozon_endpoints.STOCKS_WRITE_PATH, headers=self._headers(), json=body
                )
            except Exception as exc:
                return ActionResult.failure(exc)
            result = _ozon_result(payload)
            if not result.ok:
                return result
            responses.append(payload)
        return ActionResult.success(responses)


def _ozon_result(payload: Any) -> ActionResult:
    """Ozon answers 200 with per-item ``errors``/``updated`` flags."""
    items = payload.get("result", []) if isinstance(payload, dict) else []
    failed = [
        item
        for item in items
        if isinstance(item, dict) and (item.get("errors") or item.get("updated") is False)
    ]
    if failed:
        return ActionResult(
            ok=False,
            status_code=200,
            body=json.dumps(failed, ensure_ascii=False)[:_BODY_LIMIT],
        )
    return ActionResult.success(payload)
