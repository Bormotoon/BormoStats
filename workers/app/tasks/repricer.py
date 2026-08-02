"""Repricer — dynamic pricing based on competitor data and margin rules."""

from __future__ import annotations

from typing import Any

import structlog
from app.utils.celery_helpers import shared_task
from app.utils.runtime import get_ch_client, new_run_context
from clickhouse_connect.driver import Client

LOGGER = structlog.get_logger(__name__)


@shared_task(max_retries=3, default_retry_delay=60, name="tasks.repricer.repricer_evaluate_rules")
def repricer_evaluate_rules() -> dict[str, int]:
    """Evaluate active price rules and adjust prices via API."""
    new_run_context()
    ch = get_ch_client()
    stats = {"checked": 0, "updated": 0, "errors": 0, "skipped_min_price": 0}

    try:
        rules = _fetch_active_rules(ch)
        for rule in rules:
            stats["checked"] += 1
            try:
                _evaluate_rule(ch, rule, stats)
            except Exception:
                LOGGER.exception("repricer_rule_error", rule_id=rule["rule_id"])
                stats["errors"] += 1

        LOGGER.info("repricer_evaluate_complete", **stats)
    except Exception:
        LOGGER.exception("repricer_evaluate_failed")
        raise

    return stats


def _fetch_active_rules(ch: Client) -> list[dict[str, Any]]:
    rows = ch.query(
        "SELECT rule_id, marketplace, account_id, product_id, min_price, max_price, "
        "target_margin_percent"
        " FROM dim_price_rule FINAL WHERE is_active = 1"
    )
    return [dict(zip(rows.column_names, row, strict=True)) for row in rows.result_rows]


def _evaluate_rule(ch: Client, rule: dict[str, Any], stats: dict[str, int]) -> None:
    marketplace = rule["marketplace"]
    account_id = rule["account_id"]
    product_id = rule["product_id"]
    min_price = float(rule["min_price"])
    max_price = float(rule["max_price"])
    target_margin = float(rule["target_margin_percent"])

    be_rows = ch.query(
        "SELECT breakeven_price, current_price FROM mrt_breakeven_daily FINAL"
        " WHERE marketplace = {mp:String} AND account_id = {aid:String}"
        " AND product_id = {pid:String}"
        " ORDER BY day DESC LIMIT 1",
        parameters={"mp": marketplace, "aid": account_id, "pid": product_id},
    )
    for r in be_rows.named_results():
        breakeven = float(r["breakeven_price"])
        current = float(r["current_price"])

        target_price = breakeven * (1 + target_margin / 100) if target_margin > 0 else breakeven

        if min_price > 0 and target_price < min_price:
            target_price = min_price
            stats["skipped_min_price"] += 1

        if max_price > 0 and target_price > max_price:
            target_price = max_price

        if abs(target_price - current) > 1.0:
            _adjust_price(marketplace, account_id, product_id, target_price)
            stats["updated"] += 1


def _adjust_price(marketplace: str, account_id: str, product_id: str, new_price: float) -> None:
    LOGGER.info(
        "repricer_adjust_price",
        marketplace=marketplace,
        account_id=account_id,
        product_id=product_id,
        new_price=new_price,
    )
