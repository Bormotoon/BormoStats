"""Bidder — periodic bid management for ad campaigns.

Rules are evaluated per organization; each planned bid change is simulated
(dry-run rules, or kill switch off) or sent to the marketplace, and always
recorded in ``sys_marketplace_actions`` with before/after values.
WB bids are set per article via ``PATCH /api/advert/v1/bids``; Ozon Performance
bids are not integrated yet and are recorded as ``unsupported``.
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

from collectors.marketplace_actions import ActionResult, WbActionsClient

LOGGER = structlog.get_logger(__name__)
TASK_NAME = "tasks.bidder.bidder_evaluate_rules"
MIN_BID_DELTA = 0.01


@dataclass(frozen=True)
class BidRule:
    rule_id: str
    organization_id: str
    campaign_id: str
    marketplace: str
    account_id: str
    target_cpm: float
    max_cpm: float
    product_id: str
    placement: str
    dry_run: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> BidRule:
        return cls(
            rule_id=str(row["rule_id"]),
            organization_id=str(row["organization_id"]),
            campaign_id=str(row["campaign_id"]),
            marketplace=str(row["marketplace"]),
            account_id=str(row["account_id"]),
            target_cpm=float(row["target_cpm"]),
            max_cpm=float(row["max_cpm"]),
            product_id=str(row.get("product_id") or ""),
            placement=str(row.get("placement") or "combined"),
            dry_run=bool(row.get("dry_run", 1)),
        )


def fetch_active_rules(client: Client) -> list[BidRule]:
    rows = client.query(
        "SELECT r.rule_id AS rule_id, a.organization_id AS organization_id,"
        " r.campaign_id AS campaign_id, r.marketplace AS marketplace,"
        " r.account_id AS account_id, r.target_cpm AS target_cpm, r.max_cpm AS max_cpm,"
        " r.product_id AS product_id, r.placement AS placement, r.dry_run AS dry_run"
        " FROM dim_ad_rule AS r FINAL"
        " INNER JOIN (SELECT marketplace, account_id, organization_id FROM dim_account FINAL) AS a"
        " ON a.marketplace = r.marketplace AND a.account_id = r.account_id"
        " WHERE r.is_active = 1"
        " ORDER BY a.organization_id, r.rule_id"
    )
    return [BidRule.from_row(row) for row in rows.named_results()]


def current_cpm(client: Client, rule: BidRule) -> float | None:
    rows = client.query(
        "SELECT current_cpm FROM dim_ad_campaign FINAL"
        " WHERE campaign_id = {cid:String} AND marketplace = {mp:String}"
        " AND account_id = {aid:String} LIMIT 1",
        parameters={"cid": rule.campaign_id, "mp": rule.marketplace, "aid": rule.account_id},
    )
    for row in rows.named_results():
        value = row.get("current_cpm")
        return None if value is None else float(value)
    return None


def plan_bid_change(rule: BidRule, current: float | None) -> PlannedAction | None:
    if current is None or rule.target_cpm <= 0:
        return None
    new_cpm = rule.target_cpm
    if rule.max_cpm > 0:
        new_cpm = min(new_cpm, rule.max_cpm)
    if abs(new_cpm - current) < MIN_BID_DELTA:
        return None
    return PlannedAction(
        organization_id=rule.organization_id,
        source="bidder",
        rule_id=rule.rule_id,
        marketplace=rule.marketplace,
        account_id=rule.account_id,
        target_type="bid_cpm",
        target_id=f"{rule.campaign_id}:{rule.product_id or '*'}:{rule.placement}",
        before_value=current,
        after_value=round(new_cpm, 2),
        dry_run=rule.dry_run,
    )


def bid_executor(
    wb: WbActionsClient, rule: BidRule, action: PlannedAction
) -> Callable[[], ActionResult] | None:
    if rule.marketplace != "wb" or not wb.can_set_bids:
        return None
    if not (rule.campaign_id.isdigit() and rule.product_id.isdigit()):
        return None
    return lambda: wb.set_bid(
        advert_id=int(rule.campaign_id),
        nm_id=int(rule.product_id),
        bid_kopecks=round(action.after_value * 100),
        placement=rule.placement,
    )


@shared_task(name=TASK_NAME)
def bidder_evaluate_rules() -> dict[str, object]:
    """Evaluate active bid rules; simulate or apply bid changes with an audit trail."""
    run_id, started_at = new_run_context()
    client = get_ch_client()
    stats: Counter[str] = Counter()
    try:
        with (
            lock_scope(get_redis_client(), source="bidder", account_id="all", ttl_seconds=900),
            WbActionsClient(promotion_token=os.getenv("WB_TOKEN_PROMOTION", "")) as wb,
        ):
            budget = max_actions_per_run()
            for rule in fetch_active_rules(client):
                stats["checked"] += 1
                try:
                    action = plan_bid_change(rule, current_cpm(client, rule))
                    if action is None:
                        continue
                    if not action.dry_run and budget <= 0:
                        stats["deferred"] += 1
                        continue
                    status = execute_action(client, action, bid_executor(wb, rule, action))
                    stats[status] += 1
                    if status in (STATUS_APPLIED, STATUS_FAILED):
                        budget -= 1
                        emit_event(
                            rule.organization_id,
                            "marketplace.action",
                            {
                                "source": "bidder",
                                "status": status,
                                "rule_id": rule.rule_id,
                                "target_id": action.target_id,
                                "before": action.before_value,
                                "after": action.after_value,
                            },
                        )
                except Exception:
                    LOGGER.exception("bidder_rule_error", rule_id=rule.rule_id)
                    stats["errors"] += 1
    except LockNotAcquiredError:
        LOGGER.warning("bidder_skipped_lock_held")
        return {"run_id": run_id, "status": "skipped"}
    except Exception as exc:
        log_task_run(client, TASK_NAME, run_id, started_at, "failed", 0, str(exc), meta=dict(stats))
        raise

    log_task_run(
        client, TASK_NAME, run_id, started_at, "success", 0, "bid rules evaluated", meta=dict(stats)
    )
    LOGGER.info("bidder_evaluate_complete", **stats)
    return {"run_id": run_id, "status": "success", **stats}
