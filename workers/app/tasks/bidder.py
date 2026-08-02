"""Bidder — periodic bid management for WB and Ozon ad campaigns."""

from __future__ import annotations

import structlog
from app.celery_app import app
from app.runtime import get_ch_client, new_run_context
from clickhouse_connect.driver import Client

LOGGER = structlog.get_logger(__name__)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def bidder_evaluate_rules(self) -> dict[str, object]:
    """Evaluate active bid rules and adjust campaign bids via API."""
    new_run_context("bidder_evaluate_rules")
    ch = get_ch_client()
    stats = {"checked": 0, "updated": 0, "errors": 0}

    try:
        rules = _fetch_active_rules(ch)
        for rule in rules:
            stats["checked"] += 1
            try:
                _evaluate_rule(ch, rule, stats)
            except Exception:
                LOGGER.exception("bidder_rule_error", rule_id=rule["rule_id"])
                stats["errors"] += 1

        LOGGER.info("bidder_evaluate_complete", **stats)
    except Exception:
        LOGGER.exception("bidder_evaluate_failed")
        raise

    return stats


def _fetch_active_rules(ch: Client) -> list[dict[str, object]]:
    rows = ch.query(
        "SELECT rule_id, campaign_id, marketplace, account_id, target_cpm, max_cpm, target_position"
        " FROM dim_ad_rule FINAL WHERE is_active = 1"
    )
    return [dict(zip(rows.column_names, row, strict=True)) for row in rows.result_rows]


def _evaluate_rule(ch: Client, rule: dict[str, object], stats: dict[str, int]) -> None:
    campaign_id = rule["campaign_id"]
    marketplace = rule["marketplace"]
    account_id = rule["account_id"]
    target_cpm = float(rule["target_cpm"])
    max_cpm = float(rule["max_cpm"])

    rows = ch.query(
        "SELECT campaign_id, current_cpm FROM dim_ad_campaign FINAL"
        " WHERE campaign_id = {cid:String} AND marketplace = {mp:String}"
        " AND account_id = {aid:String}",
        parameters={"cid": campaign_id, "mp": marketplace, "aid": account_id},
    )
    for r in rows.named_results():
        current_cpm = r.get("current_cpm")
        if current_cpm is None:
            continue

        current_cpm = float(current_cpm)
        if target_cpm > 0 and current_cpm != target_cpm:
            new_cpm = target_cpm
            if max_cpm > 0 and new_cpm > max_cpm:
                new_cpm = max_cpm
            _adjust_bid(marketplace, account_id, campaign_id, new_cpm)
            stats["updated"] += 1


def _adjust_bid(marketplace: str, account_id: str, campaign_id: str, new_cpm: float) -> None:
    LOGGER.info(
        "bidder_adjust_bid",
        marketplace=marketplace,
        account_id=account_id,
        campaign_id=campaign_id,
        new_cpm=new_cpm,
    )
