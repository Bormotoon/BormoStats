"""Transform tasks from raw to stg."""

from __future__ import annotations

from celery import shared_task

from app.utils.locking import LockNotAcquired
from app.utils.rebuilds import LOGGER as REBUILD_LOGGER
from app.utils.rebuilds import rebuild_task_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

WB_SALES_TO_STG_SQL = """
INSERT INTO stg_sales
(
  event_ts,
  marketplace,
  account_id,
  order_id,
  posting_number,
  srid,
  product_id,
  nm_id,
  ozon_product_id,
  offer_id,
  qty,
  price_gross,
  payout,
  is_return,
  last_change_ts,
  meta_json,
  ingested_at
)
SELECT
  event_ts,
  'wb' AS marketplace,
  account_id,
  srid AS order_id,
  NULL AS posting_number,
  srid,
  toString(nm_id) AS product_id,
  nm_id,
  NULL AS ozon_product_id,
  NULL AS offer_id,
  if(is_return = 1, -toInt32(quantity), toInt32(quantity)) AS qty,
  price_rub AS price_gross,
  payout_rub AS payout,
  is_return,
  last_change_ts,
  payload AS meta_json,
  ingested_at
FROM raw_wb_sales FINAL
WHERE event_ts >= now() - toIntervalDay({days})
"""

WB_ORDERS_TO_STG_SQL = """
INSERT INTO stg_orders
(
  event_ts,
  marketplace,
  account_id,
  order_id,
  status,
  product_id,
  qty,
  price_gross,
  last_change_ts,
  meta_json,
  ingested_at
)
SELECT
  event_ts,
  'wb' AS marketplace,
  account_id,
  srid AS order_id,
  'new' AS status,
  toString(nm_id) AS product_id,
  toInt32(quantity) AS qty,
  price_rub AS price_gross,
  last_change_ts,
  payload AS meta_json,
  ingested_at
FROM raw_wb_orders FINAL
WHERE event_ts >= now() - toIntervalDay({days})
"""

WB_STOCKS_TO_STG_SQL = """
INSERT INTO stg_stocks
(
  snapshot_ts,
  marketplace,
  account_id,
  product_id,
  nm_id,
  ozon_product_id,
  offer_id,
  warehouse_id,
  amount,
  reserved,
  present,
  meta_json,
  ingested_at
)
SELECT
  snapshot_ts,
  'wb' AS marketplace,
  account_id,
  toString(chrt_id) AS product_id,
  nm_id,
  NULL AS ozon_product_id,
  sku AS offer_id,
  warehouse_id,
  amount,
  NULL AS reserved,
  NULL AS present,
  payload AS meta_json,
  ingested_at
FROM raw_wb_stocks FINAL
WHERE snapshot_ts >= now() - toIntervalDay({days})
"""

WB_FUNNEL_TO_STG_SQL = """
INSERT INTO stg_funnel_daily
(
  day,
  marketplace,
  account_id,
  product_id,
  nm_id,
  views,
  adds_to_cart,
  orders,
  orders_sum,
  buyouts,
  cancels,
  add_to_cart_conv,
  cart_to_order_conv,
  buyout_percent,
  wishlist,
  currency,
  meta_json,
  ingested_at
)
SELECT
  day,
  'wb' AS marketplace,
  account_id,
  toString(nm_id) AS product_id,
  nm_id,
  open_card_count AS views,
  add_to_cart_count AS adds_to_cart,
  orders_count AS orders,
  orders_sum_rub AS orders_sum,
  buyouts_count AS buyouts,
  cancel_count AS cancels,
  add_to_cart_conv,
  cart_to_order_conv,
  buyout_percent,
  add_to_wishlist AS wishlist,
  currency,
  payload AS meta_json,
  ingested_at
FROM raw_wb_funnel_daily FINAL
WHERE day >= today() - {days}
"""

OZON_SALES_TO_STG_SQL = """
INSERT INTO stg_sales
(
  event_ts,
  marketplace,
  account_id,
  order_id,
  posting_number,
  srid,
  product_id,
  nm_id,
  ozon_product_id,
  offer_id,
  qty,
  price_gross,
  payout,
  is_return,
  last_change_ts,
  meta_json,
  ingested_at
)
SELECT
  p.created_at AS event_ts,
  'ozon' AS marketplace,
  i.account_id,
  i.posting_number AS order_id,
  i.posting_number,
  NULL AS srid,
  toString(i.ozon_product_id) AS product_id,
  NULL AS nm_id,
  i.ozon_product_id,
  i.offer_id,
  toInt32(i.quantity) AS qty,
  i.price AS price_gross,
  i.payout,
  0 AS is_return,
  p.created_at AS last_change_ts,
  i.payload AS meta_json,
  i.ingested_at
FROM
  (
    SELECT *
    FROM raw_ozon_posting_items FINAL
  ) i
LEFT JOIN
  (
    SELECT *
    FROM raw_ozon_postings FINAL
  ) p
  ON i.account_id = p.account_id
 AND i.posting_number = p.posting_number
WHERE i.ingested_at >= now() - toIntervalDay({days})
"""

OZON_ORDERS_TO_STG_SQL = """
INSERT INTO stg_orders
(
  event_ts,
  marketplace,
  account_id,
  order_id,
  status,
  product_id,
  qty,
  price_gross,
  last_change_ts,
  meta_json,
  ingested_at
)
SELECT
  created_at AS event_ts,
  'ozon' AS marketplace,
  account_id,
  posting_number AS order_id,
  status,
  NULL AS product_id,
  NULL AS qty,
  NULL AS price_gross,
  in_process_at AS last_change_ts,
  payload AS meta_json,
  ingested_at
FROM raw_ozon_postings FINAL
WHERE created_at >= now() - toIntervalDay({days})
"""

OZON_STOCKS_TO_STG_SQL = """
INSERT INTO stg_stocks
(
  snapshot_ts,
  marketplace,
  account_id,
  product_id,
  nm_id,
  ozon_product_id,
  offer_id,
  warehouse_id,
  amount,
  reserved,
  present,
  meta_json,
  ingested_at
)
SELECT
  snapshot_ts,
  'ozon' AS marketplace,
  account_id,
  toString(ozon_product_id) AS product_id,
  NULL AS nm_id,
  ozon_product_id,
  offer_id,
  warehouse_id,
  present - reserved AS amount,
  reserved,
  present,
  payload AS meta_json,
  ingested_at
FROM raw_ozon_stocks FINAL
WHERE snapshot_ts >= now() - toIntervalDay({days})
"""

OZON_ADS_TO_STG_SQL = """
INSERT INTO stg_ads_daily
(
  day,
  marketplace,
  account_id,
  campaign_id,
  impressions,
  clicks,
  cost,
  orders,
  revenue,
  meta_json,
  ingested_at
)
SELECT
  day,
  'ozon' AS marketplace,
  account_id,
  campaign_id,
  impressions,
  clicks,
  cost,
  orders,
  revenue,
  payload AS meta_json,
  ingested_at
FROM raw_ozon_ads_daily FINAL
WHERE day >= today() - {days}
"""

OZON_FINANCE_TO_STG_SQL = """
INSERT INTO stg_finance_ops
(
  operation_ts,
  marketplace,
  account_id,
  operation_id,
  type,
  amount,
  currency,
  meta_json,
  ingested_at
)
SELECT
  operation_ts,
  'ozon' AS marketplace,
  account_id,
  operation_id,
  type,
  amount,
  currency,
  payload AS meta_json,
  ingested_at
FROM raw_ozon_finance_ops FINAL
WHERE operation_ts >= now() - toIntervalDay({days})
"""

SYNC_DIM_PRODUCT_WB_SQL = """
INSERT INTO dim_product
(
  marketplace,
  account_id,
  product_id,
  nm_id,
  chrt_id,
  sku,
  offer_id,
  ozon_product_id,
  title,
  brand,
  category,
  updated_at
)
SELECT
  'wb' AS marketplace,
  account_id,
  toString(nm_id) AS product_id,
  nm_id,
  chrt_id,
  any(barcode) AS sku,
  any(barcode) AS offer_id,
  NULL AS ozon_product_id,
  NULL AS title,
  NULL AS brand,
  NULL AS category,
  now() AS updated_at
FROM raw_wb_sales FINAL
WHERE event_ts >= now() - toIntervalDay({days})
GROUP BY account_id, nm_id, chrt_id
"""

SYNC_DIM_PRODUCT_OZON_SQL = """
INSERT INTO dim_product
(
  marketplace,
  account_id,
  product_id,
  nm_id,
  chrt_id,
  sku,
  offer_id,
  ozon_product_id,
  title,
  brand,
  category,
  updated_at
)
SELECT
  'ozon' AS marketplace,
  i.account_id,
  toString(i.ozon_product_id) AS product_id,
  NULL AS nm_id,
  NULL AS chrt_id,
  any(i.offer_id) AS sku,
  any(i.offer_id) AS offer_id,
  i.ozon_product_id,
  any(i.name) AS title,
  NULL AS brand,
  NULL AS category,
  now() AS updated_at
FROM
  (
    SELECT *
    FROM raw_ozon_posting_items FINAL
  ) i
WHERE i.ingested_at >= now() - toIntervalDay({days})
GROUP BY i.account_id, i.ozon_product_id
"""

STG_REBUILD_TABLES = (
    ("stg_sales", "day"),
    ("stg_orders", "day"),
    ("stg_stocks", "day"),
    ("stg_funnel_daily", "day"),
)

STG_LONG_REBUILD_TABLES = (
    ("stg_ads_daily", "day"),
    ("stg_finance_ops", "day"),
)


def _run_transform(days: int, task_name: str) -> dict[str, int | str]:
    run_id, started_at = new_run_context(task_name)
    client = get_ch_client()
    redis_client = get_redis_client()
    try:
        with rebuild_task_scope(
            redis_client=redis_client,
            task_lock_source=task_name.rsplit(".", maxsplit=1)[-1],
        ):
            ads_days = max(days, 60)
            client.command("SET mutations_sync = 1")
            for table_name, day_column in STG_REBUILD_TABLES:
                client.command(
                    f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= today() - {days}"
                )
            for table_name, day_column in STG_LONG_REBUILD_TABLES:
                client.command(
                    f"ALTER TABLE {table_name} DELETE WHERE {day_column} >= today() - {ads_days}"
                )

            client.command(WB_SALES_TO_STG_SQL.format(days=days))
            client.command(WB_ORDERS_TO_STG_SQL.format(days=days))
            client.command(WB_STOCKS_TO_STG_SQL.format(days=days))
            client.command(WB_FUNNEL_TO_STG_SQL.format(days=days))
            client.command(OZON_SALES_TO_STG_SQL.format(days=days))
            client.command(OZON_ORDERS_TO_STG_SQL.format(days=days))
            client.command(OZON_STOCKS_TO_STG_SQL.format(days=days))
            client.command(OZON_ADS_TO_STG_SQL.format(days=ads_days))
            client.command(OZON_FINANCE_TO_STG_SQL.format(days=ads_days))
            client.command(SYNC_DIM_PRODUCT_WB_SQL.format(days=max(days, 30)))
            client.command(SYNC_DIM_PRODUCT_OZON_SQL.format(days=max(days, 30)))
        log_task_run(
            client,
            task_name,
            run_id,
            started_at,
            "success",
            0,
            f"transform done for {days} days",
        )
        return {"status": "success", "days": days, "run_id": run_id}
    except LockNotAcquired as exc:
        REBUILD_LOGGER.warning(
            "rebuild_launch_skipped task_name=%s reason=lock_conflict error=%s",
            task_name,
            str(exc),
        )
        log_task_run(
            client,
            task_name,
            run_id,
            started_at,
            "skipped",
            0,
            "transform skipped: conflicting rebuild lock",
            meta={"reason": "lock_not_acquired", "conflict": True},
        )
        return {"status": "skipped", "reason": "lock_not_acquired", "run_id": run_id}
    except Exception as exc:
        log_task_run(client, task_name, run_id, started_at, "failed", 0, str(exc))
        raise


@shared_task(name="tasks.transforms.transform_all_recent")
def transform_all_recent() -> dict[str, int | str]:
    return _run_transform(days=14, task_name="tasks.transforms.transform_all_recent")


@shared_task(name="tasks.transforms.transform_backfill_days")
def transform_backfill_days(days: int = 14) -> dict[str, int | str]:
    safe_days = max(1, min(days, 365))
    return _run_transform(days=safe_days, task_name="tasks.transforms.transform_backfill_days")
