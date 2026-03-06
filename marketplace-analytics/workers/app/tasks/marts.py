"""Tasks for building analytics marts."""

from __future__ import annotations

from celery import shared_task

from app.utils.runtime import get_ch_client, log_task_run, new_run_context

MRT_SALES_DAILY_SQL = """
INSERT INTO mrt_sales_daily
SELECT
  s.day,
  s.marketplace,
  s.account_id,
  s.product_id,
  sum(s.qty) AS qty,
  sumIf(s.price_gross * s.qty, s.is_return = 0) AS revenue,
  sum(s.payout) AS payout,
  sumIf(s.qty, s.is_return = 1) AS returns_qty,
  now() AS updated_at
FROM stg_sales s
WHERE s.day >= today() - {days}
GROUP BY s.day, s.marketplace, s.account_id, s.product_id
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
  f.day,
  f.marketplace,
  f.account_id,
  f.product_id,
  sum(f.views) AS views,
  sum(f.adds_to_cart) AS adds_to_cart,
  sum(f.orders) AS orders,
  if(sum(f.views) = 0, 0, sum(f.orders) / sum(f.views)) AS cr_order,
  if(sum(f.views) = 0, 0, sum(f.adds_to_cart) / sum(f.views)) AS cr_cart,
  now() AS updated_at
FROM stg_funnel_daily f
WHERE f.day >= today() - {days}
GROUP BY f.day, f.marketplace, f.account_id, f.product_id
"""

MRT_ADS_DAILY_SQL = """
INSERT INTO mrt_ads_daily
SELECT
  a.day,
  a.marketplace,
  a.account_id,
  a.campaign_id,
  sum(a.impressions) AS impressions,
  sum(a.clicks) AS clicks,
  sum(a.cost) AS cost,
  sum(a.orders) AS orders,
  sum(a.revenue) AS revenue,
  if(sum(a.revenue) = 0, 0, sum(a.cost) / sum(a.revenue)) AS acos,
  if(sum(a.cost) = 0, 0, (sum(a.revenue) - sum(a.cost)) / sum(a.cost)) AS romi,
  now() AS updated_at
FROM stg_ads_daily a
WHERE a.day >= today() - {days}
GROUP BY a.day, a.marketplace, a.account_id, a.campaign_id
"""

MART_REBUILD_TABLES = (
    ("mrt_sales_daily", "day"),
    ("mrt_stock_daily", "day"),
    ("mrt_funnel_daily", "day"),
)


def _run_marts(days: int, task_name: str) -> dict[str, str | int]:
    run_id, started_at = new_run_context(task_name)
    client = get_ch_client()

    try:
        ads_days = max(days, 60)
        client.command("SET mutations_sync = 1")
        for table_name, day_column in MART_REBUILD_TABLES:
            client.command(f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= today() - {days}")
        client.command(f"ALTER TABLE mrt_ads_daily DELETE WHERE day >= today() - {ads_days}")

        client.command(MRT_SALES_DAILY_SQL.format(days=days))
        client.command(MRT_STOCK_DAILY_SQL.format(days=days))
        client.command(MRT_FUNNEL_DAILY_SQL.format(days=days))
        client.command(MRT_ADS_DAILY_SQL.format(days=ads_days))
        log_task_run(client, task_name, run_id, started_at, "success", 0, f"marts built for {days} days")
        return {"run_id": run_id, "status": "success", "days": days}
    except Exception as exc:
        log_task_run(client, task_name, run_id, started_at, "failed", 0, str(exc))
        raise


@shared_task(name="tasks.marts.build_marts_recent")
def build_marts_recent() -> dict[str, str | int]:
    return _run_marts(days=14, task_name="tasks.marts.build_marts_recent")


@shared_task(name="tasks.marts.build_marts_backfill_days")
def build_marts_backfill_days(days: int = 14) -> dict[str, str | int]:
    safe_days = max(1, min(days, 365))
    return _run_marts(days=safe_days, task_name="tasks.marts.build_marts_backfill_days")
