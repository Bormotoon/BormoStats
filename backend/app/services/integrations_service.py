"""Integrations: marketplace stock push and webhook subscriptions (per organization)."""

from __future__ import annotations

import secrets
import uuid
from collections import defaultdict
from typing import Any

import structlog
from app.core.config import Settings
from app.db.ch import insert_values_sql, utc_now
from app.models.integrations import (
    StockUpdateItem,
    StockUpdateResult,
    WebhookLog,
    WebhookSubscription,
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
    WebhookSubscriptionWithSecret,
)
from app.services.task_queue import send_task
from clickhouse_connect.driver import Client

from collectors.marketplace_actions import OzonActionsClient, WbActionsClient
from common.secret_box import encrypt_secret
from common.url_safety import validate_outbound_url
from common.webhooks import EVENT_TYPES, WILDCARD_EVENT

LOGGER = structlog.get_logger(__name__)

DISPATCH_TASK = "tasks.webhooks.dispatch_event"
DELIVER_TASK = "tasks.webhooks.deliver_to_subscription"

_SUB_COLUMNS: tuple[tuple[str, str], ...] = (
    ("subscription_id", "String"),
    ("organization_id", "String"),
    ("name", "String"),
    ("endpoint_url", "String"),
    ("secret", "String"),
    ("events", "Array(String)"),
    ("is_active", "UInt8"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_SUB_COLS = ", ".join(name for name, _ in _SUB_COLUMNS)
_SUB_INSERT = insert_values_sql("webhook_subscriptions", _SUB_COLUMNS)
_LOG_COLS = (
    "log_id, organization_id, subscription_id, event_id, event_type, attempt, status,"
    " request_body, response_body, response_status, success, duration_ms, next_retry_at,"
    " created_at"
)


class InvalidSubscriptionError(ValueError):
    """Raised for unsupported events or unsafe endpoint URLs."""


class IntegrationsService:
    def __init__(self, ch: Client, settings: Settings, organization_id: str) -> None:
        self._ch = ch
        self._settings = settings
        self._org = organization_id

    # -- Stock Update ------------------------------------------------------------

    def push_stock(
        self, items: list[StockUpdateItem], marketplace: str | None = None
    ) -> list[StockUpdateResult]:
        results: list[StockUpdateResult] = []
        if marketplace is None or marketplace == "wb":
            results.append(self._push_wb_stock(items))
        if marketplace is None or marketplace == "ozon":
            results.append(self._push_ozon_stock(items))
        self.emit_event(
            "stock.update.completed",
            {
                "items": len(items),
                "results": [result.model_dump() for result in results],
            },
        )
        return results

    def _push_wb_stock(self, items: list[StockUpdateItem]) -> StockUpdateResult:
        token = self._settings.wb_marketplace_token
        if not token:
            return StockUpdateResult(
                marketplace="wb", success=False, errors=["WB_TOKEN_MARKETPLACE not configured"]
            )
        by_warehouse: dict[int, list[tuple[int, int]]] = defaultdict(list)
        errors: list[str] = []
        for item in items:
            if item.warehouse_id is None:
                errors.append(f"{item.sku}: warehouse_id is required for WB")
            elif not item.sku.isdigit():
                errors.append(f"{item.sku}: WB expects the numeric size id (chrtId) as sku")
            else:
                by_warehouse[item.warehouse_id].append((int(item.sku), item.stock))
        if not by_warehouse:
            return StockUpdateResult(marketplace="wb", success=False, errors=errors)
        with WbActionsClient(marketplace_token=token) as client:
            for warehouse_id, amounts in by_warehouse.items():
                result = client.set_stocks(warehouse_id, amounts)
                if not result.ok:
                    LOGGER.warning(
                        "wb_stock_push_failed", status=result.status_code, body=result.body
                    )
                    errors.append(
                        f"warehouse {warehouse_id}: HTTP {result.status_code} {result.body}"
                    )
        return StockUpdateResult(marketplace="wb", success=not errors, errors=errors)

    def _push_ozon_stock(self, items: list[StockUpdateItem]) -> StockUpdateResult:
        client_id = self._settings.ozon_client_id
        api_key = self._settings.ozon_api_key
        if not client_id or not api_key:
            return StockUpdateResult(
                marketplace="ozon",
                success=False,
                errors=["OZON_CLIENT_ID or OZON_API_KEY not configured"],
            )
        stocks = [
            (item.sku, item.stock, item.warehouse_id)
            for item in items
            if item.warehouse_id is not None
        ]
        if not stocks:
            return StockUpdateResult(
                marketplace="ozon",
                success=False,
                errors=["No items with warehouse_id — required for Ozon stock update"],
            )
        with OzonActionsClient(client_id=client_id, api_key=api_key) as client:
            result = client.set_stocks(stocks)
        if not result.ok:
            LOGGER.warning("ozon_stock_push_failed", status=result.status_code, body=result.body)
            return StockUpdateResult(
                marketplace="ozon",
                success=False,
                errors=[f"HTTP {result.status_code} {result.body}"],
            )
        return StockUpdateResult(marketplace="ozon", success=True)

    # -- Webhook Subscriptions ---------------------------------------------------

    def _validate(self, endpoint_url: str | None, events: list[str] | None) -> None:
        if events is not None:
            unknown = sorted(set(events) - EVENT_TYPES - {WILDCARD_EVENT})
            if unknown:
                raise InvalidSubscriptionError(f"unsupported events: {', '.join(unknown)}")
        if endpoint_url is not None:
            try:
                validate_outbound_url(
                    endpoint_url, allow_private=self._settings.webhook_allow_private_targets
                )
            except ValueError as exc:
                raise InvalidSubscriptionError(f"endpoint_url rejected: {exc}") from exc

    def list_subscriptions(self) -> list[WebhookSubscription]:
        rows = self._ch.query(
            f"SELECT {_SUB_COLS} FROM webhook_subscriptions FINAL"
            " WHERE organization_id = {oid:String} ORDER BY created_at DESC",
            parameters={"oid": self._org},
        )
        return [_row_to_sub(r)[0] for r in rows.named_results()]

    def _get(self, subscription_id: str) -> tuple[WebhookSubscription, str] | None:
        rows = self._ch.query(
            f"SELECT {_SUB_COLS} FROM webhook_subscriptions FINAL"
            " WHERE organization_id = {oid:String} AND subscription_id = {sid:String} LIMIT 1",
            parameters={"oid": self._org, "sid": subscription_id},
        )
        for r in rows.named_results():
            return _row_to_sub(r)
        return None

    def get_subscription(self, subscription_id: str) -> WebhookSubscription | None:
        found = self._get(subscription_id)
        return found[0] if found else None

    def create_subscription(self, data: WebhookSubscriptionCreate) -> WebhookSubscriptionWithSecret:
        self._validate(data.endpoint_url, data.events)
        now = utc_now()
        secret = secrets.token_urlsafe(32)
        sub = WebhookSubscription(
            subscription_id=str(uuid.uuid4()),
            organization_id=self._org,
            name=data.name,
            endpoint_url=data.endpoint_url.strip(),
            events=sorted(set(data.events)),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._write(sub, encrypt_secret(secret, self._settings.webhook_secret_key))
        return WebhookSubscriptionWithSecret(**sub.model_dump(), secret=secret)

    def update_subscription(
        self, subscription_id: str, data: WebhookSubscriptionUpdate
    ) -> WebhookSubscription | None:
        found = self._get(subscription_id)
        if found is None:
            return None
        self._validate(data.endpoint_url, data.events)
        existing, encrypted_secret = found
        changes = data.model_dump(exclude_none=True)
        if "events" in changes:
            changes["events"] = sorted(set(changes["events"]))
        sub = existing.model_copy(update={**changes, "updated_at": utc_now()})
        self._write(sub, encrypted_secret)
        return sub

    def rotate_secret(self, subscription_id: str) -> WebhookSubscriptionWithSecret | None:
        found = self._get(subscription_id)
        if found is None:
            return None
        secret = secrets.token_urlsafe(32)
        sub = found[0].model_copy(update={"updated_at": utc_now()})
        self._write(sub, encrypt_secret(secret, self._settings.webhook_secret_key))
        return WebhookSubscriptionWithSecret(**sub.model_dump(), secret=secret)

    def delete_subscription(self, subscription_id: str) -> bool:
        if self._get(subscription_id) is None:
            return False
        self._ch.command(
            "ALTER TABLE webhook_subscriptions DELETE"
            " WHERE organization_id = {oid:String} AND subscription_id = {sid:String}",
            parameters={"oid": self._org, "sid": subscription_id},
        )
        return True

    def send_test(self, subscription_id: str) -> str | None:
        if self._get(subscription_id) is None:
            return None
        event_id = str(uuid.uuid4())
        send_task(
            self._settings,
            DELIVER_TASK,
            kwargs={
                "organization_id": self._org,
                "subscription_id": subscription_id,
                "event_id": event_id,
                "event_type": "webhook.test",
                "payload": {"message": "BormoStats webhook test delivery"},
            },
        )
        return event_id

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Queue fan-out of an event to the organization's subscribers (best effort)."""
        try:
            send_task(
                self._settings,
                DISPATCH_TASK,
                kwargs={
                    "organization_id": self._org,
                    "event_type": event_type,
                    "payload": payload,
                    "event_id": str(uuid.uuid4()),
                },
            )
        except Exception as exc:
            LOGGER.warning("webhook_event_enqueue_failed", event_type=event_type, error=str(exc))

    # -- Webhook Logs ------------------------------------------------------------

    def list_logs(self, limit: int = 200) -> list[WebhookLog]:
        rows = self._ch.query(
            f"SELECT {_LOG_COLS} FROM webhook_logs"
            " WHERE organization_id = {oid:String}"
            " ORDER BY created_at DESC LIMIT {lim:UInt32}",
            parameters={"oid": self._org, "lim": limit},
        )
        return [WebhookLog(**{**r, "success": bool(r["success"])}) for r in rows.named_results()]

    def _write(self, sub: WebhookSubscription, encrypted_secret: str) -> None:
        self._ch.command(
            _SUB_INSERT,
            parameters={
                "subscription_id": sub.subscription_id,
                "organization_id": sub.organization_id,
                "name": sub.name,
                "endpoint_url": sub.endpoint_url,
                "secret": encrypted_secret,
                "events": sub.events,
                "is_active": 1 if sub.is_active else 0,
                "created_at": sub.created_at or utc_now(),
                "updated_at": sub.updated_at or utc_now(),
            },
        )


def _row_to_sub(r: dict[str, Any]) -> tuple[WebhookSubscription, str]:
    encrypted_secret = r.get("secret") or ""
    sub = WebhookSubscription(
        subscription_id=r["subscription_id"],
        organization_id=r["organization_id"],
        name=r["name"],
        endpoint_url=r["endpoint_url"],
        events=list(r.get("events") or []),
        is_active=bool(r.get("is_active", 1)),
        has_secret=bool(encrypted_secret),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )
    return sub, encrypted_secret
