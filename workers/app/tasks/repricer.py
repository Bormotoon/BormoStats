"""Repricer — margin-based price management.

For every active price rule the target price is derived from the latest
break-even price and the rule's margin, clamped to ``[min_price, max_price]``.
Changes are simulated for dry-run rules (or with the kill switch off) and applied
through the marketplace price APIs otherwise; all outcomes are audited in
``sys_marketplace_actions``.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from app.utils.celery_helpers import shared_task
from app.utils.events import emit_event
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.marketplace_actions import (
    STATUS_APPLIED,
    STATUS_FAILED,
    PlannedAction,
    execute_action,
    max_actions_per_run,
)
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context
from clickhouse_connect.driver import Client

from collectors.marketplace_actions import ActionResult, OzonActionsClient, WbActionsClient

LOGGER = structlog.get_logger(__name__)
TASK_NAME = "tasks.repricer.repricer_evaluate_rules"
MIN_PRICE_DELTA = 1.0


@dataclass(frozen=True)
class PriceRule:
    rule_id: str
    organization_id: str
    marketplace: str
    account_id: str
    product_id: str
    min_price: float
    max_price: float
    target_margin_percent: float
    dry_run: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PriceRule:
        return cls(
            rule_id=str(row["rule_id"]),
            organization_id=str(row["organization_id"]),
            marketplace=str(row["marketplace"]),
            account_id=str(row["account_id"]),
            product_id=str(row["product_id"]),
            min_price=float(row["min_price"]),
            max_price=float(row["max_price"]),
            target_margin_percent=float(row["target_margin_percent"]),
            dry_run=bool(row.get("dry_run", 1)),
        )


@dataclass(frozen=True)
class Breakeven:
    breakeven_price: float
    current_price: float


def fetch_active_rules(client: Client) -> list[PriceRule]:
    rows = client.query(
        "SELECT r.rule_id AS rule_id, a.organization_id AS organization_id,"
        " r.marketplace AS marketplace, r.account_id AS account_id,"
        " r.product_id AS product_id, r.min_price AS min_price, r.max_price AS max_price,"
        " r.target_margin_percent AS target_margin_percent, r.dry_run AS dry_run"
        " FROM dim_price_rule AS r FINAL"
        " INNER JOIN (SELECT marketplace, account_id, organization_id FROM dim_account FINAL) AS a"
        " ON a.marketplace = r.marketplace AND a.account_id = r.account_id"
        " WHERE r.is_active = 1"
        " ORDER BY a.organization_id, r.rule_id"
    )
    return [PriceRule.from_row(row) for row in rows.named_results()]


def latest_breakeven(client: Client, rule: PriceRule) -> Breakeven | None:
    rows = client.query(
        "SELECT breakeven_price, current_price FROM mrt_breakeven_daily FINAL"
        " WHERE marketplace = {mp:String} AND account_id = {aid:String}"
        " AND product_id = {pid:String}"
        " ORDER BY day DESC LIMIT 1",
        parameters={"mp": rule.marketplace, "aid": rule.account_id, "pid": rule.product_id},
    )
    for row in rows.named_results():
        return Breakeven(
            breakeven_price=float(row["breakeven_price"]),
            current_price=float(row["current_price"]),
        )
    return None


def target_price(rule: PriceRule, breakeven: Breakeven) -> tuple[float, bool]:
    """Return the clamped target price and whether it was raised to ``min_price``."""
    price = breakeven.breakeven_price * (1 + max(0.0, rule.target_margin_percent) / 100)
    clamped_to_min = False
    if rule.min_price > 0 and price < rule.min_price:
        price = rule.min_price
        clamped_to_min = True
    if rule.max_price > 0 and price > rule.max_price:
        price = rule.max_price
    return round(price, 2), clamped_to_min


def plan_price_change(rule: PriceRule, breakeven: Breakeven | None) -> PlannedAction | None:
    if breakeven is None or breakeven.breakeven_price <= 0:
        return None
    price, _ = target_price(rule, breakeven)
    if abs(price - breakeven.current_price) <= MIN_PRICE_DELTA:
        return None
    return PlannedAction(
        organization_id=rule.organization_id,
        source="repricer",
        rule_id=rule.rule_id,
        marketplace=rule.marketplace,
        account_id=rule.account_id,
        target_type="price",
        target_id=rule.product_id,
        before_value=breakeven.current_price,
        after_value=price,
        dry_run=rule.dry_run,
    )


def price_executor(
    wb: WbActionsClient,
    ozon: OzonActionsClient,
    rule: PriceRule,
    action: PlannedAction,
) -> Callable[[], ActionResult] | None:
    if rule.marketplace == "wb" and wb.can_set_prices and rule.product_id.isdigit():
        # WB takes the list price (before the seller discount) as a whole number.
        return lambda: wb.set_price(nm_id=int(rule.product_id), price=round(action.after_value))
    if rule.marketplace == "ozon" and ozon.configured:
        return lambda: ozon.set_price(offer_id=rule.product_id, price=action.after_value)
    return None


@shared_task(name=TASK_NAME)
def repricer_evaluate_rules() -> dict[str, object]:
    """Evaluate active price rules; simulate or apply price changes with an audit trail."""
    run_id, started_at = new_run_context()
    client = get_ch_client()
    stats: Counter[str] = Counter()
    try:
        with (
            lock_scope(get_redis_client(), source="repricer", account_id="all", ttl_seconds=900),
            WbActionsClient(prices_token=os.getenv("WB_TOKEN_PRICES", "")) as wb,
            OzonActionsClient(
                client_id=os.getenv("OZON_CLIENT_ID", ""), api_key=os.getenv("OZON_API_KEY", "")
            ) as ozon,
        ):
            budget = max_actions_per_run()
            for rule in fetch_active_rules(client):
                stats["checked"] += 1
                try:
                    breakeven = latest_breakeven(client, rule)
                    if breakeven is not None and target_price(rule, breakeven)[1]:
                        stats["clamped_to_min_price"] += 1
                    action = plan_price_change(rule, breakeven)
                    if action is None:
                        continue
                    if not action.dry_run and budget <= 0:
                        stats["deferred"] += 1
                        continue
                    status = execute_action(client, action, price_executor(wb, ozon, rule, action))
                    stats[status] += 1
                    if status in (STATUS_APPLIED, STATUS_FAILED):
                        budget -= 1
                        emit_event(
                            rule.organization_id,
                            "marketplace.action",
                            {
                                "source": "repricer",
                                "status": status,
                                "rule_id": rule.rule_id,
                                "target_id": action.target_id,
                                "before": action.before_value,
                                "after": action.after_value,
                            },
                        )
                except Exception:
                    LOGGER.exception("repricer_rule_error", rule_id=rule.rule_id)
                    stats["errors"] += 1
    except LockNotAcquiredError:
        LOGGER.warning("repricer_skipped_lock_held")
        return {"run_id": run_id, "status": "skipped"}
    except Exception as exc:
        log_task_run(client, TASK_NAME, run_id, started_at, "failed", 0, str(exc), meta=dict(stats))
        raise

    log_task_run(
        client,
        TASK_NAME,
        run_id,
        started_at,
        "success",
        0,
        "price rules evaluated",
        meta=dict(stats),
    )
    LOGGER.info("repricer_evaluate_complete", **stats)
    return {"run_id": run_id, "status": "success", **stats}
