from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import httpx
import structlog
from app.models.integrations import (
    StockUpdateItem,
    StockUpdateResult,
    WebhookLog,
    WebhookSubscription,
    WebhookSubscriptionCreate,
)
from clickhouse_connect.driver import Client

LOGGER = structlog.get_logger(__name__)

WB_STOCKS_WRITE_PATH = "/api/v2/stocks"
WB_STATISTICS_BASE = "https://statistics-api.wildberries.ru"
OZON_BASE = "https://api-seller.ozon.ru"
OZON_STOCKS_WRITE_PATH = "/v1/product/import/stocks"


class IntegrationsService:
    def __init__(
        self,
        ch: Client,
        wb_token: str = "",
        ozon_client_id: str = "",
        ozon_api_key: str = "",
    ) -> None:
        self._ch = ch
        self._wb_token = wb_token
        self._ozon_client_id = ozon_client_id
        self._ozon_api_key = ozon_api_key

    # -- Stock Update ------------------------------------------------------------

    def push_stock(
        self, items: list[StockUpdateItem], marketplace: str | None = None
    ) -> list[StockUpdateResult]:
        results: list[StockUpdateResult] = []

        if marketplace is None or marketplace == "wb":
            results.append(self._push_wb_stock(items))

        if marketplace is None or marketplace == "ozon":
            results.append(self._push_ozon_stock(items))

        return results

    def _push_wb_stock(self, items: list[StockUpdateItem]) -> StockUpdateResult:
        if not self._wb_token:
            return StockUpdateResult(
                marketplace="wb", success=False, errors=["WB_TOKEN_STATISTICS not configured"]
            )

        body = [
            {
                "barcode": item.sku,
                "stock": item.stock,
                "warehouseId": item.warehouse_id,
            }
            for item in items
            if item.warehouse_id is not None
        ]

        if not body:
            return StockUpdateResult(
                marketplace="wb",
                success=False,
                errors=["No items with warehouse_id — required for WB stock update"],
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{WB_STATISTICS_BASE}{WB_STOCKS_WRITE_PATH}",
                    headers={"Authorization": self._wb_token},
                    json=body,
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                if data.get("error"):
                    err_text = data.get("errorText", "unknown")
                    return StockUpdateResult(marketplace="wb", success=False, errors=[err_text])
                return StockUpdateResult(marketplace="wb", success=True)
        except httpx.HTTPError as exc:
            return StockUpdateResult(marketplace="wb", success=False, errors=[str(exc)])

    def _push_ozon_stock(self, items: list[StockUpdateItem]) -> StockUpdateResult:
        if not self._ozon_client_id or not self._ozon_api_key:
            return StockUpdateResult(
                marketplace="ozon",
                success=False,
                errors=["OZON_CLIENT_ID or OZON_API_KEY not configured"],
            )

        body = {
            "stocks": [
                {
                    "offer_id": item.sku,
                    "stock": item.stock,
                    "warehouse_id": item.warehouse_id,
                }
                for item in items
                if item.warehouse_id is not None
            ]
        }

        if not body["stocks"]:
            return StockUpdateResult(
                marketplace="ozon",
                success=False,
                errors=["No items with warehouse_id — required for Ozon stock update"],
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{OZON_BASE}{OZON_STOCKS_WRITE_PATH}",
                    headers={
                        "Client-Id": self._ozon_client_id,
                        "Api-Key": self._ozon_api_key,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                return StockUpdateResult(marketplace="ozon", success=True)
        except httpx.HTTPError as exc:
            return StockUpdateResult(marketplace="ozon", success=False, errors=[str(exc)])

    # -- Webhook Subscriptions ---------------------------------------------------

    def list_subscriptions(self, organization_id: str) -> list[WebhookSubscription]:
        rows = self._ch.query(
            "SELECT subscription_id, organization_id, name, endpoint_url, secret,"
            " events, is_active, created_at, updated_at"
            " FROM webhook_subscriptions FINAL"
            " WHERE organization_id = {oid:String}"
            " ORDER BY created_at DESC",
            parameters={"oid": organization_id},
        )
        return [_row_to_sub(r) for r in rows.named_results()]

    def create_subscription(self, data: WebhookSubscriptionCreate) -> WebhookSubscription:
        sub_id = str(uuid.uuid4())[:12]
        now = datetime.utcnow()
        self._ch.command(
            "INSERT INTO webhook_subscriptions"
            " (subscription_id, organization_id, name, endpoint_url, secret, events, "
            "is_active, created_at, updated_at)"
            " VALUES ({sid:String}, {oid:String}, {name:String}, {url:String}, {secret:String},"
            " {events:Array(String)}, 1, {created:DateTime}, {updated:DateTime})",
            parameters={
                "sid": sub_id,
                "oid": "default",
                "name": data.name,
                "url": data.endpoint_url,
                "secret": data.secret,
                "events": data.events,
                "created": now,
                "updated": now,
            },
        )
        return WebhookSubscription(
            subscription_id=sub_id,
            organization_id="default",
            name=data.name,
            endpoint_url=data.endpoint_url,
            secret=data.secret,
            events=data.events,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    def delete_subscription(self, subscription_id: str) -> bool:
        self._ch.command(
            "ALTER TABLE webhook_subscriptions DELETE WHERE subscription_id = {sid:String}",
            parameters={"sid": subscription_id},
        )
        return True

    # -- Webhook Logs ------------------------------------------------------------

    def list_logs(self, organization_id: str) -> list[WebhookLog]:
        rows = self._ch.query(
            "SELECT log_id, organization_id, subscription_id, event_type, request_body,"
            " response_body, response_status, success, created_at"
            " FROM webhook_logs"
            " WHERE organization_id = {oid:String}"
            " ORDER BY created_at DESC LIMIT 200",
            parameters={"oid": organization_id},
        )
        return [WebhookLog(**r) for r in rows.named_results()]


def _row_to_sub(r: dict[str, Any]) -> WebhookSubscription:
    return WebhookSubscription(
        subscription_id=r["subscription_id"],
        organization_id=r["organization_id"],
        name=r["name"],
        endpoint_url=r["endpoint_url"],
        secret=r.get("secret", ""),
        events=r.get("events") or [],
        is_active=bool(r.get("is_active", 1)),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )
