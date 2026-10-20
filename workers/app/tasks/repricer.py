"""Repricer — keeps the price a rule asks for.

A rule names a card by supplier article (``product_id`` = WB vendorCode / Ozon offer_id) and
says what to keep (``mode``):

* ``buyer_price``  — the price the buyer pays after the marketplace's own discount (WB SPP,
  Ozon co-financed discounts). The seller price is ``target / (1 - discount)``, with the
  discount measured on the card's recent sales (``mrt_price_current``); on WB, whose SPP is
  much the same across a seller's cards, the account's median is used for a card with too
  few orders. While the discount cannot be measured the rule waits, unless its
  ``no_discount_fallback`` says to use the account's median discount (``account_median``) or
  to keep ``target`` as the seller price (``seller_price``) meanwhile;
* ``seller_price`` — the seller's price after the seller's discount;
* ``margin``       — break-even price plus ``target_margin_percent``.

The price is then clamped to ``[min_price, max_price]`` and never below break-even (when the
cost price is known), and one change moves it by at most ``max_step_pct`` — WB and Ozon
quarantine sharp changes. WB gets a new list price with the card's discount kept, Ozon a new
price with the crossed-out price scaled alongside.

After a live change the rule waits for the next catalogue snapshot before acting again.
Changes are simulated for dry-run rules (or with the kill switch off) and applied through the
marketplace price APIs otherwise; all outcomes are audited in ``sys_marketplace_actions``.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

MODE_BUYER_PRICE = "buyer_price"
MODE_SELLER_PRICE = "seller_price"
MODE_MARGIN = "margin"
MODES = (MODE_BUYER_PRICE, MODE_SELLER_PRICE, MODE_MARGIN)
# what a buyer-price rule does without a usable discount; "" waits for the card's sales
FALLBACK_ACCOUNT_MEDIAN = "account_median"
FALLBACK_SELLER_PRICE = "seller_price"

MIN_PRICE_DELTA = 1.0
# changes under half a percent are noise: the measured discount moves a little every day
MIN_PRICE_DELTA_PCT = 0.5
DEFAULT_MAX_STEP_PCT = 10.0
# a buyer-price rule acts on a discount measured on 3+ of the card's own sales, or on WB on the
# account's median over 10+ orders (Ozon's discounts vary too much between cards for that)
MIN_DISCOUNT_SAMPLES = 3
MIN_ACCOUNT_DISCOUNT_SAMPLES = 10
ACCOUNT_DISCOUNT_MARKETPLACES = frozenset({"wb"})
MAX_DISCOUNT_PCT = 90.0
# a price snapshot older than this is not acted upon
MAX_SNAPSHOT_AGE = timedelta(hours=6)


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
    mode: str = MODE_MARGIN
    target_price: float = 0.0
    max_step_pct: float = DEFAULT_MAX_STEP_PCT
    no_discount_fallback: str = ""

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
            mode=str(row.get("mode") or MODE_MARGIN),
            target_price=float(row.get("target_price") or 0),
            max_step_pct=float(row.get("max_step_pct") or DEFAULT_MAX_STEP_PCT),
            no_discount_fallback=str(row.get("no_discount_fallback") or ""),
        )


@dataclass(frozen=True)
class PriceSnapshot:
    """One card of ``mrt_price_current``: the current price and what it is made of."""

    product_id: str
    list_price: float
    seller_discount_pct: float
    seller_price: float
    mp_discount_pct: float | None
    mp_discount_scope: str
    mp_discount_samples: int
    breakeven_price: float | None
    price_seen_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PriceSnapshot:
        return cls(
            product_id=str(row["product_id"]),
            list_price=float(row["list_price"]),
            seller_discount_pct=float(row["seller_discount_pct"]),
            seller_price=float(row["seller_price"]),
            mp_discount_pct=_opt_float(row.get("mp_discount_pct")),
            mp_discount_scope=str(row.get("mp_discount_scope") or ""),
            mp_discount_samples=int(row.get("mp_discount_samples") or 0),
            breakeven_price=_opt_float(row.get("breakeven_price")),
            price_seen_at=_as_utc(row["price_seen_at"]),
        )


@dataclass(frozen=True)
class PriceDecision:
    """The seller price to set, or why there is none (``price`` is None)."""

    price: float | None
    reason: str
    clamped_to_min: bool = False
    # the no_discount_fallback the price was computed with, "" when none was needed
    fallback: str = ""


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def fetch_active_rules(client: Client) -> list[PriceRule]:
    rows = client.query(
        "SELECT r.rule_id AS rule_id, a.organization_id AS organization_id,"
        " r.marketplace AS marketplace, r.account_id AS account_id,"
        " r.product_id AS product_id, r.min_price AS min_price, r.max_price AS max_price,"
        " r.target_margin_percent AS target_margin_percent, r.dry_run AS dry_run,"
        " r.mode AS mode, r.target_price AS target_price, r.max_step_pct AS max_step_pct,"
        " r.no_discount_fallback AS no_discount_fallback"
        " FROM dim_price_rule AS r FINAL"
        " INNER JOIN (SELECT marketplace, account_id, organization_id FROM dim_account FINAL) AS a"
        " ON a.marketplace = r.marketplace AND a.account_id = r.account_id"
        " WHERE r.is_active = 1"
        " ORDER BY a.organization_id, r.rule_id"
    )
    return [PriceRule.from_row(row) for row in rows.named_results()]


def fetch_snapshot(client: Client, rule: PriceRule) -> PriceSnapshot | None:
    rows = client.query(
        "SELECT product_id, list_price, seller_discount_pct, seller_price, mp_discount_pct,"
        " mp_discount_scope, mp_discount_samples, breakeven_price, price_seen_at"
        " FROM mrt_price_current FINAL"
        " WHERE marketplace = {mp:String} AND account_id = {aid:String}"
        " AND offer_id = {offer:String}"
        " LIMIT 1",
        parameters={"mp": rule.marketplace, "aid": rule.account_id, "offer": rule.product_id},
    )
    for row in rows.named_results():
        return PriceSnapshot.from_row(row)
    return None


def last_applied_at(client: Client, rule: PriceRule) -> datetime | None:
    """When this card's price was last changed live by the repricer."""
    rows = client.query(
        "SELECT max(created_at) AS ts, count() AS n FROM sys_marketplace_actions"
        " WHERE source = 'repricer' AND status = {applied:String}"
        " AND marketplace = {mp:String} AND account_id = {aid:String}"
        " AND target_id = {offer:String}",
        parameters={
            "applied": STATUS_APPLIED,
            "mp": rule.marketplace,
            "aid": rule.account_id,
            "offer": rule.product_id,
        },
    )
    for row in rows.named_results():
        return _as_utc(row["ts"]) if row["n"] else None
    return None


def discount_usable(marketplace: str, snap: PriceSnapshot) -> bool:
    """Whether the measured marketplace discount is solid enough to set a price on."""
    discount = snap.mp_discount_pct
    if discount is None or not 0 <= discount < MAX_DISCOUNT_PCT:
        return False
    if snap.mp_discount_scope == "product":
        return snap.mp_discount_samples >= MIN_DISCOUNT_SAMPLES
    if snap.mp_discount_scope == "account":
        return (
            marketplace in ACCOUNT_DISCOUNT_MARKETPLACES
            and snap.mp_discount_samples >= MIN_ACCOUNT_DISCOUNT_SAMPLES
        )
    return False


def desired_price(rule: PriceRule, snap: PriceSnapshot) -> PriceDecision:
    """The seller price the rule asks for, before the step limit."""
    fallback = ""
    if rule.mode == MODE_BUYER_PRICE:
        discount = snap.mp_discount_pct
        if rule.target_price <= 0:
            return PriceDecision(None, "no_discount_data")
        if discount is not None and discount_usable(rule.marketplace, snap):
            price = rule.target_price / (1 - discount / 100)
        elif (
            rule.no_discount_fallback == FALLBACK_ACCOUNT_MEDIAN
            and discount is not None
            and 0 <= discount < MAX_DISCOUNT_PCT
        ):
            # the mart falls back to the account's median for a card without its own sales
            fallback = FALLBACK_ACCOUNT_MEDIAN
            price = rule.target_price / (1 - discount / 100)
        elif rule.no_discount_fallback == FALLBACK_SELLER_PRICE:
            fallback = FALLBACK_SELLER_PRICE
            price = rule.target_price
        else:
            return PriceDecision(None, "no_discount_data")
    elif rule.mode == MODE_SELLER_PRICE:
        if rule.target_price <= 0:
            return PriceDecision(None, "no_target")
        price = rule.target_price
    elif rule.mode == MODE_MARGIN:
        if not snap.breakeven_price or snap.breakeven_price <= 0:
            return PriceDecision(None, "no_cost")
        price = snap.breakeven_price * (1 + max(0.0, rule.target_margin_percent) / 100)
    else:
        return PriceDecision(None, "unknown_mode")

    clamped_to_min = False
    floor = max(rule.min_price, snap.breakeven_price or 0.0)
    if floor > 0 and price < floor:
        price = floor
        clamped_to_min = True
    if rule.max_price > 0 and price > rule.max_price:
        price = rule.max_price
    return PriceDecision(round(price), "ok", clamped_to_min, fallback)


def step_limited(current: float, desired: float, max_step_pct: float) -> float:
    """Move from ``current`` towards ``desired`` by at most ``max_step_pct`` percent."""
    step = current * max(0.1, max_step_pct) / 100
    if desired > current + step:
        return float(round(current + step))
    if desired < current - step:
        return float(round(current - step))
    return desired


def plan_price_change(
    rule: PriceRule, snap: PriceSnapshot | None, *, now: datetime | None = None
) -> tuple[PlannedAction | None, str]:
    """Plan the change of the seller price; the second item says why there is none."""
    action, reason, _ = _plan(rule, snap, now)
    return action, reason


def _plan(
    rule: PriceRule, snap: PriceSnapshot | None, now: datetime | None
) -> tuple[PlannedAction | None, str, str]:
    """``plan_price_change`` plus the no-discount fallback the price was computed with."""
    if snap is None:
        return None, "no_snapshot", ""
    if snap.seller_price <= 0:
        return None, "no_price", ""
    if (now or datetime.now(UTC)) - snap.price_seen_at > MAX_SNAPSHOT_AGE:
        return None, "stale_snapshot", ""
    decision = desired_price(rule, snap)
    if decision.price is None:
        return None, decision.reason, ""
    price = step_limited(snap.seller_price, decision.price, rule.max_step_pct)
    tolerance = max(MIN_PRICE_DELTA, snap.seller_price * MIN_PRICE_DELTA_PCT / 100)
    if abs(price - snap.seller_price) <= tolerance:
        return None, "in_tolerance", decision.fallback
    action = PlannedAction(
        organization_id=rule.organization_id,
        source="repricer",
        rule_id=rule.rule_id,
        marketplace=rule.marketplace,
        account_id=rule.account_id,
        target_type="price",
        target_id=rule.product_id,
        before_value=snap.seller_price,
        after_value=price,
        dry_run=rule.dry_run,
    )
    reason = "clamped_to_min" if decision.clamped_to_min else "planned"
    return action, reason, decision.fallback


def wb_list_price(seller_price: float, discount_pct: float) -> int:
    """WB takes the list price as a whole number; the seller price is list x (1 - discount)."""
    return round(seller_price / (1 - min(max(discount_pct, 0.0), 99.0) / 100))


def ozon_old_price(snap: PriceSnapshot, new_price: float) -> float:
    """The crossed-out price scaled with the price, so the shown discount stays the same."""
    if snap.list_price <= snap.seller_price or snap.seller_price <= 0:
        return 0.0
    return float(round(new_price * snap.list_price / snap.seller_price))


def price_executor(
    wb: WbActionsClient,
    ozon: OzonActionsClient,
    rule: PriceRule,
    snap: PriceSnapshot,
    action: PlannedAction,
) -> Callable[[], ActionResult] | None:
    if rule.marketplace == "wb" and wb.can_set_prices and snap.product_id.isdigit():
        discount = round(snap.seller_discount_pct)
        return lambda: wb.set_price(
            nm_id=int(snap.product_id),
            price=wb_list_price(action.after_value, discount),
            discount=discount,
        )
    if rule.marketplace == "ozon" and ozon.configured:
        return lambda: ozon.set_price(
            offer_id=rule.product_id,
            price=action.after_value,
            old_price=ozon_old_price(snap, action.after_value),
        )
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
                    snap = fetch_snapshot(client, rule)
                    action, reason, fallback = _plan(rule, snap, None)
                    if fallback:
                        stats[f"fallback_{fallback}"] += 1
                    if action is None or snap is None:
                        stats[reason] += 1
                        continue
                    if reason == "clamped_to_min":
                        stats["clamped_to_min_price"] += 1
                    applied_at = last_applied_at(client, rule)
                    if not action.dry_run and applied_at and applied_at >= snap.price_seen_at:
                        # the snapshot predates our last change: wait for the marketplace
                        stats["awaiting_snapshot"] += 1
                        continue
                    if not action.dry_run and budget <= 0:
                        stats["deferred"] += 1
                        continue
                    executor = price_executor(wb, ozon, rule, snap, action)
                    status = execute_action(client, action, executor)
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
