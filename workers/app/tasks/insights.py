"""Actionable Insights — scans marts for anomalies and generates tasks."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import structlog
from app.celery_app import app
from app.runtime import get_ch_client, new_run_context

from automation.actions.telegram import TelegramAction

LOGGER = structlog.get_logger(__name__)
INSERT_COLS = (
    "task_id, organization_id, trigger_type, marketplace, account_id, product_id, "
    "campaign_id, title, description, priority, status, created_at, resolved_at"
)


def _insert_task(ch, task: dict[str, object]) -> None:
    ch.command(
        f"INSERT INTO dim_actionable_task ({INSERT_COLS})"
        " VALUES ({tid:String}, {oid:String}, {tt:String}, {mp:String}, {aid:String},"
        " {pid:Nullable(String)}, {cid:Nullable(String)}, {title:String}, {desc:String},"
        " {prio:String}, {status:String}, {created:DateTime}, {resolved:Nullable(DateTime)})",
        parameters=task,
    )


@app.task(bind=True, max_retries=2)
def generate_actionable_tasks(self) -> dict[str, int]:
    ch = get_ch_client()
    new_run_context("generate_actionable_tasks")
    stats = {"inserted": 0}

    now = datetime.utcnow()
    orgs = ch.query("SELECT DISTINCT organization_id FROM dim_organization FINAL")
    org_ids = [r[0] for r in orgs.result_rows] or ["default"]

    for org_id in org_ids:
        try:
            stats["inserted"] += _trigger_turnover(ch, org_id, now)
            stats["inserted"] += _trigger_stagnant(ch, org_id, now)
            stats["inserted"] += _trigger_bad_ads(ch, org_id, now)
        except Exception:
            LOGGER.exception("insights_trigger_error", organization_id=org_id)

    LOGGER.info("insights_generated", **stats)
    return stats


def _trigger_turnover(ch, org_id: str, now: datetime) -> int:
    rows = ch.query(
        "SELECT marketplace, account_id, product_id, avg(stock_end) AS avg_stock,"
        " avg(qty) AS avg_daily_sales, if(avg(qty) > 0, avg(stock_end) / avg(qty), "
        "999) AS turnover_days"
        " FROM mrt_sales_daily WHERE day >= now() - 14 GROUP BY marketplace, account_id, product_id"
        " HAVING turnover_days < 10"
    )
    count = 0
    for r in rows.result_rows:
        tid = str(uuid.uuid4())[:8]
        mp, aid, pid, stock, sales, turnover = r
        _insert_task(
            ch,
            {
                "tid": tid,
                "oid": org_id,
                "tt": "turnover",
                "mp": mp,
                "aid": aid,
                "pid": str(pid),
                "cid": None,
                "title": f"Нужна поставка: {mp}/{pid}",
                "desc": (
                    f"Оборачиваемость {float(turnover):.0f} дней. "
                    f"Остаток {float(stock):.0f}, среднедневные продажи {float(sales):.0f}. "
                    f"Рекомендуется поставка > {float(sales):.0f} шт."
                ),
                "prio": "high",
                "status": "open",
                "created": now,
                "resolved": None,
            },
        )
        count += 1
    return count


def _trigger_stagnant(ch, org_id: str, now: datetime) -> int:
    rows = ch.query(
        "SELECT a.marketplace, a.account_id, a.product_id, a.revenue_60d, s.stock_end"
        " FROM mrt_abc_xyz_analysis a"
        " JOIN mrt_stock_daily s ON a.marketplace = s.marketplace AND a.account_id = s.account_id"
        "  AND a.product_id = s.product_id AND s.day = now() - 1"
        " WHERE a.abc_class = 'C' AND s.stock_end > 100"
    )
    count = 0
    for r in rows.result_rows:
        tid = str(uuid.uuid4())[:8]
        mp, aid, pid, rev, stock = r
        _insert_task(
            ch,
            {
                "tid": tid,
                "oid": org_id,
                "tt": "stagnant",
                "mp": mp,
                "aid": aid,
                "pid": str(pid),
                "cid": None,
                "title": f"Зависший товар: {mp}/{pid}",
                "desc": (
                    f"ABC=C, остаток {float(stock):.0f}, выручка 60д {float(rev):.0f}₽. "
                    "Снизьте цену или запустите акцию."
                ),
                "prio": "medium",
                "status": "open",
                "created": now,
                "resolved": None,
            },
        )
        count += 1
    return count


def _trigger_bad_ads(ch, org_id: str, now: datetime) -> int:
    rows = ch.query(
        "SELECT marketplace, account_id, campaign_id, sum(cost) AS cost_14d, "
        "sum(orders) AS orders_14d"
        " FROM mrt_ads_daily WHERE day >= now() - 14"
        " GROUP BY marketplace, account_id, campaign_id"
        " HAVING cost_14d > 0 AND orders_14d = 0"
    )
    count = 0
    for r in rows.result_rows:
        tid = str(uuid.uuid4())[:8]
        mp, aid, cid, cost, _ = r
        _insert_task(
            ch,
            {
                "tid": tid,
                "oid": org_id,
                "tt": "bad_ad",
                "mp": mp,
                "aid": aid,
                "pid": None,
                "cid": cid,
                "title": f"Неэффективная РК: {mp}/{cid}",
                "desc": (
                    f"Расходы {float(cost):.0f}₽ за 14 дней, 0 заказов. Рекомендуется отключить."
                ),
                "prio": "high",
                "status": "open",
                "created": now,
                "resolved": None,
            },
        )
        count += 1
    return count


@app.task(bind=True, max_retries=2)
def send_daily_digest(self) -> dict[str, object]:
    ch = get_ch_client()
    new_run_context("send_daily_digest")
    telegram = TelegramAction(
        bot_token=os.getenv("TG_BOT_TOKEN", ""),
        chat_id=os.getenv("TG_CHAT_ID", ""),
    )

    if not telegram.enabled:
        LOGGER.warning("daily_digest_skipped_no_telegram_config")
        return {"sent": False, "reason": "telegram not configured"}

    rows = ch.query(
        "SELECT trigger_type, priority, count() AS cnt"
        " FROM dim_actionable_task"
        " WHERE status = 'open'"
        " GROUP BY trigger_type, priority"
        " ORDER BY trigger_type, priority"
    )

    if not rows.result_rows:
        msg = "✅ *Утренний дайджест*\n\nНет открытых задач. Всё чисто!"
        telegram.execute("daily_digest", {}, msg)
        return {"sent": True, "tasks": 0}

    lines = ["☀️ *Утренний дайджест*", ""]
    total = 0
    high_total = 0
    labels = {"turnover": "🚚 Поставки", "stagnant": "📦 Зависшие товары", "bad_ad": "📢 Реклама"}

    for _trigger_type, priority, cnt in rows.result_rows:
        total += cnt
        if priority == "high":
            high_total += cnt

    for trigger_type, priority, cnt in rows.result_rows:
        label = labels.get(trigger_type, trigger_type)
        icon = "🔴" if priority == "high" else "🟡"
        lines.append(f"{icon} *{label}* ({priority}): {cnt} задач")

    lines.append("")
    lines.append(f"Итого: {total} задач (🔥 {high_total} высокого приоритета)")
    lines.append("")
    lines.append("Открой дашборд: https://bormostats.local/insights")

    msg = "\n".join(lines)
    telegram.execute("daily_digest", {}, msg)
    LOGGER.info("daily_digest_sent", total=total)
    return {"sent": True, "tasks": total}
