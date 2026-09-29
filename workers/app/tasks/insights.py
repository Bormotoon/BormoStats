"""Actionable Insights — scans marts per organization and generates tasks.

Generation is idempotent: every recommendation has a ``dedupe_key`` (org, trigger,
marketplace, account, product/campaign). A new task is created only when no task
with the same key is open/in progress and none was dismissed in the last
``DISMISS_SUPPRESSION_DAYS`` days.
"""

from __future__ import annotations

import os
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from app.utils.celery_helpers import shared_task
from app.utils.events import emit_event
from app.utils.runtime import get_ch_client, log_task_run, new_run_context
from clickhouse_connect.driver import Client

from automation.actions.telegram import TelegramAction
from common.insights import (
    ACTIVE_STATUSES,
    DISMISS_SUPPRESSION_DAYS,
    TASK_INSERT,
    dedupe_key,
)
from common.tenancy_sql import account_scope_sql

LOGGER = structlog.get_logger(__name__)
GENERATE_TASK_NAME = "tasks.insights.generate_actionable_tasks"
DIGEST_TASK_NAME = "tasks.insights.send_daily_digest"
_SCOPE = account_scope_sql("oid")

TURNOVER_SQL = f"""
WITH
  sales AS (
    SELECT marketplace, account_id, product_id, sum(qty) / 14 AS avg_daily_sales
    FROM mrt_sales_daily
    WHERE day >= today() - 14 AND {_SCOPE}
    GROUP BY marketplace, account_id, product_id
  ),
  stock AS (
    SELECT marketplace, account_id, product_id, sum(stock_end) AS stock_end
    FROM mrt_stock_daily
    WHERE day = (SELECT max(day) FROM mrt_stock_daily WHERE {_SCOPE}) AND {_SCOPE}
    GROUP BY marketplace, account_id, product_id
  )
SELECT s.marketplace, s.account_id, s.product_id, st.stock_end, s.avg_daily_sales,
       st.stock_end / s.avg_daily_sales AS turnover_days
FROM sales AS s
INNER JOIN stock AS st USING (marketplace, account_id, product_id)
WHERE s.avg_daily_sales > 0 AND turnover_days < 10
"""

STAGNANT_SQL = f"""
SELECT a.marketplace, a.account_id, a.product_id, a.revenue_60d, st.stock_end
FROM (
  SELECT marketplace, account_id, product_id,
         argMax(revenue_60d, day) AS revenue_60d, argMax(abc_class, day) AS abc_class
  FROM mrt_abc_xyz_analysis FINAL
  WHERE {_SCOPE}
  GROUP BY marketplace, account_id, product_id
) AS a
INNER JOIN (
  SELECT marketplace, account_id, product_id, sum(stock_end) AS stock_end
  FROM mrt_stock_daily
  WHERE day = today() - 1 AND {_SCOPE}
  GROUP BY marketplace, account_id, product_id
) AS st USING (marketplace, account_id, product_id)
WHERE a.abc_class = 'C' AND st.stock_end > 100
"""

BAD_ADS_SQL = f"""
SELECT marketplace, account_id, campaign_id, sum(cost) AS cost_14d, sum(orders) AS orders_14d
FROM mrt_ads_daily
WHERE day >= today() - 14 AND {_SCOPE}
GROUP BY marketplace, account_id, campaign_id
HAVING cost_14d > 0 AND orders_14d = 0
"""


@dataclass(frozen=True)
class Recommendation:
    trigger_type: str
    marketplace: str
    account_id: str
    product_id: str | None
    campaign_id: str | None
    title: str
    description: str
    priority: str


def turnover_recommendations(client: Client, org_id: str) -> list[Recommendation]:
    rows = client.query(TURNOVER_SQL, parameters={"oid": org_id}).result_rows
    return [
        Recommendation(
            trigger_type="turnover",
            marketplace=str(mp),
            account_id=str(aid),
            product_id=str(pid),
            campaign_id=None,
            title=f"Нужна поставка: {mp}/{pid}",
            description=(
                f"Оборачиваемость {float(turnover):.0f} дн. Остаток {float(stock):.0f}, "
                f"среднедневные продажи {float(sales):.1f}. "
                f"Рекомендуется поставка ≥ {float(sales) * 14:.0f} шт."
            ),
            priority="high",
        )
        for mp, aid, pid, stock, sales, turnover in rows
    ]


def stagnant_recommendations(client: Client, org_id: str) -> list[Recommendation]:
    rows = client.query(STAGNANT_SQL, parameters={"oid": org_id}).result_rows
    return [
        Recommendation(
            trigger_type="stagnant",
            marketplace=str(mp),
            account_id=str(aid),
            product_id=str(pid),
            campaign_id=None,
            title=f"Зависший товар: {mp}/{pid}",
            description=(
                f"ABC=C, остаток {float(stock):.0f}, выручка 60д {float(rev):.0f}₽. "
                "Снизьте цену или запустите акцию."
            ),
            priority="medium",
        )
        for mp, aid, pid, rev, stock in rows
    ]


def bad_ads_recommendations(client: Client, org_id: str) -> list[Recommendation]:
    rows = client.query(BAD_ADS_SQL, parameters={"oid": org_id}).result_rows
    return [
        Recommendation(
            trigger_type="bad_ad",
            marketplace=str(mp),
            account_id=str(aid),
            product_id=None,
            campaign_id=str(cid),
            title=f"Неэффективная РК: {mp}/{cid}",
            description=(
                f"Расходы {float(cost):.0f}₽ за 14 дней, 0 заказов. Рекомендуется отключить."
            ),
            priority="high",
        )
        for mp, aid, cid, cost, _ in rows
    ]


TRIGGERS = (turnover_recommendations, stagnant_recommendations, bad_ads_recommendations)


def existing_dedupe_keys(client: Client, org_id: str) -> set[str]:
    rows = client.query(
        "SELECT DISTINCT dedupe_key FROM dim_actionable_task FINAL"
        " WHERE organization_id = {oid:String} AND dedupe_key != ''"
        " AND (status IN {active:Array(String)}"
        "      OR (status = 'dismissed'"
        "          AND resolved_at >= now() - toIntervalDay({days:UInt16})))",
        parameters={
            "oid": org_id,
            "active": list(ACTIVE_STATUSES),
            "days": DISMISS_SUPPRESSION_DAYS,
        },
    ).result_rows
    return {str(row[0]) for row in rows}


def insert_new_tasks(
    client: Client,
    org_id: str,
    recommendations: list[Recommendation],
    now: datetime,
) -> list[dict[str, object]]:
    known = existing_dedupe_keys(client, org_id)
    created: list[dict[str, object]] = []
    for rec in recommendations:
        key = dedupe_key(
            org_id,
            rec.trigger_type,
            rec.marketplace,
            rec.account_id,
            rec.product_id,
            rec.campaign_id,
        )
        if key in known:
            continue
        known.add(key)
        params: dict[str, object] = {
            "task_id": str(uuid.uuid4()),
            "organization_id": org_id,
            "trigger_type": rec.trigger_type,
            "marketplace": rec.marketplace,
            "account_id": rec.account_id,
            "product_id": rec.product_id,
            "campaign_id": rec.campaign_id,
            "title": rec.title,
            "description": rec.description,
            "priority": rec.priority,
            "status": "open",
            "dedupe_key": key,
            "created_at": now,
            "resolved_at": None,
        }
        client.command(TASK_INSERT, parameters=params)
        created.append(params)
    return created


def organization_ids(client: Client) -> list[str]:
    rows = client.query("SELECT DISTINCT organization_id FROM dim_organization FINAL").result_rows
    return [str(r[0]) for r in rows] or ["default"]


@shared_task(name=GENERATE_TASK_NAME)
def generate_actionable_tasks() -> dict[str, object]:
    run_id, started_at = new_run_context()
    client = get_ch_client()
    now = datetime.now(UTC).replace(microsecond=0)
    stats: Counter[str] = Counter()

    for org_id in organization_ids(client):
        recommendations: list[Recommendation] = []
        for trigger in TRIGGERS:
            try:
                recommendations.extend(trigger(client, org_id))
            except Exception:
                LOGGER.exception(
                    "insights_trigger_error", organization_id=org_id, trigger=trigger.__name__
                )
                stats["trigger_errors"] += 1
        created = insert_new_tasks(client, org_id, recommendations, now)
        stats["candidates"] += len(recommendations)
        stats["inserted"] += len(created)
        if created:
            emit_event(
                org_id,
                "insight.created",
                {
                    "count": len(created),
                    "tasks": [
                        {k: t[k] for k in ("task_id", "trigger_type", "title", "priority")}
                        for t in created[:50]
                    ],
                },
            )

    status = "failed" if stats["trigger_errors"] else "success"
    log_task_run(
        client,
        GENERATE_TASK_NAME,
        run_id,
        started_at,
        status,
        stats["inserted"],
        "insights generated",
        meta=dict(stats),
    )
    LOGGER.info("insights_generated", **stats)
    return {"run_id": run_id, "status": status, **stats}


DIGEST_LABELS = {
    "turnover": "🚚 Поставки",
    "stagnant": "📦 Зависшие товары",
    "bad_ad": "📢 Реклама",
}


def build_digest(rows: list[tuple[str, str, str, int]], dashboard_url: str) -> tuple[str, int]:
    if not rows:
        return "✅ *Утренний дайджест*\n\nНет открытых задач. Всё чисто!", 0
    lines = ["☀️ *Утренний дайджест*"]
    total = sum(int(cnt) for *_, cnt in rows)
    high_total = sum(int(cnt) for _, _, priority, cnt in rows if priority == "high")
    multiple_orgs = len({org for org, *_ in rows}) > 1
    current_org: str | None = None
    for org_id, trigger_type, priority, cnt in rows:
        if multiple_orgs and org_id != current_org:
            lines.extend(["", f"🏢 *{org_id}*"])
            current_org = org_id
        elif current_org is None:
            lines.append("")
            current_org = org_id
        label = DIGEST_LABELS.get(trigger_type, trigger_type)
        icon = "🔴" if priority == "high" else "🟡"
        lines.append(f"{icon} *{label}* ({priority}): {cnt} задач")
    lines.extend(["", f"Итого: {total} задач (🔥 {high_total} высокого приоритета)"])
    if dashboard_url:
        lines.extend(["", f"Открой дашборд: {dashboard_url}"])
    return "\n".join(lines), total


@shared_task(name=DIGEST_TASK_NAME)
def send_daily_digest() -> dict[str, object]:
    client = get_ch_client()
    telegram = TelegramAction(
        bot_token=os.getenv("TG_BOT_TOKEN", ""),
        chat_id=os.getenv("TG_CHAT_ID", ""),
    )
    if not telegram.enabled:
        LOGGER.warning("daily_digest_skipped_no_telegram_config")
        return {"sent": False, "reason": "telegram not configured"}

    rows = client.query(
        "SELECT organization_id, trigger_type, priority, count() AS cnt"
        " FROM dim_actionable_task FINAL"
        " WHERE status IN {active:Array(String)}"
        " GROUP BY organization_id, trigger_type, priority"
        " ORDER BY organization_id, trigger_type, priority",
        parameters={"active": list(ACTIVE_STATUSES)},
    ).result_rows
    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    message, total = build_digest(
        [(str(o), str(t), str(p), int(c)) for o, t, p, c in rows],
        f"{base_url}/ui/#/dashboard" if base_url else "",
    )
    telegram.execute("daily_digest", {}, message)
    LOGGER.info("daily_digest_sent", total=total)
    return {"sent": True, "tasks": total}
