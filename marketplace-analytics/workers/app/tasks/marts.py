"""Tasks for building analytics marts."""

from __future__ import annotations

from celery import shared_task

from app.utils.runtime import get_ch_client, log_task_run, new_run_context

MRT_SALES_DAILY_SQL = """
INSERT INTO mrt_sales_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  sum(qty) AS qty,
  sumIf(price_gross * qty, is_return=0) AS revenue,
  sum(payout) AS payout,
  sumIf(qty, is_return=1) AS returns_qty,
  now() AS updated_at
FROM stg_sales
WHERE day >= today() - {days}
GROUP BY day, marketplace, account_id, product_id
"""

MRT_STOCK_DAILY_SQL = """
INSERT INTO mrt_stock_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  warehouse_id,
  argMax(amount, snapshot_ts) AS stock_end,
  now() AS updated_at
FROM stg_stocks
WHERE day >= today() - {days}
GROUP BY day, marketplace, account_id, product_id, warehouse_id
"""

MRT_FUNNEL_DAILY_SQL = """
INSERT INTO mrt_funnel_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  sum(views) AS views,
  sum(adds_to_cart) AS adds_to_cart,
  sum(orders) AS orders,
  if(sum(views)=0, 0, sum(orders)/sum(views)) AS cr_order,
  if(sum(views)=0, 0, sum(adds_to_cart)/sum(views)) AS cr_cart,
  now() AS updated_at
FROM stg_funnel_daily
WHERE day >= today() - {days}
GROUP BY day, marketplace, account_id, product_id
"""

MRT_ADS_DAILY_SQL = """
INSERT INTO mrt_ads_daily
SELECT
  day,
  marketplace,
  account_id,
  campaign_id,
  sum(impressions) AS impressions,
  sum(clicks) AS clicks,
  sum(cost) AS cost,
  sum(orders) AS orders,
  sum(revenue) AS revenue,
  if(sum(revenue)=0, 0, sum(cost)/sum(revenue)) AS acos,
  if(sum(cost)=0, 0, (sum(revenue)-sum(cost))/sum(cost)) AS romi,
  now() AS updated_at
FROM stg_ads_daily
WHERE day >= today() - {days}
GROUP BY day, marketplace, account_id, campaign_id
"""


def _run_marts(days: int, task_name: str) -> dict[str, str | int]:
    run_id, started_at = new_run_context(task_name)
    client = get_ch_client()

    try:
        client.command(MRT_SALES_DAILY_SQL.format(days=days))
        client.command(MRT_STOCK_DAILY_SQL.format(days=days))
        client.command(MRT_FUNNEL_DAILY_SQL.format(days=days))
        ads_days = max(days, 60)
        client.command(MRT_ADS_DAILY_SQL.format(days=ads_days))
        log_task_run(client, task_name, run_id, started_at, "success", 0, f"marts built for {days} days")
        return {"run_id": run_id, "status": "success", "days": days}
    except Exception as exc:
        log_task_run(client, task_name, run_id, started_at, "failed", 0, str(exc))
        raise
    finally:
        client.close()


@shared_task(name="tasks.marts.build_marts_recent")
def build_marts_recent() -> dict[str, str | int]:
    return _run_marts(days=14, task_name="tasks.marts.build_marts_recent")


@shared_task(name="tasks.marts.build_marts_backfill_days")
def build_marts_backfill_days(days: int = 14) -> dict[str, str | int]:
    safe_days = max(1, min(days, 365))
    return _run_marts(days=safe_days, task_name="tasks.marts.build_marts_backfill_days")
