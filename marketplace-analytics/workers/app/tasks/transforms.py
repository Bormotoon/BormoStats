"""Transform tasks from raw to stg."""

from __future__ import annotations

from celery import shared_task

from app.utils.runtime import get_ch_client, log_task_run, new_run_context

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
FROM raw_wb_sales
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
FROM raw_wb_orders
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
FROM raw_wb_stocks
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
FROM raw_wb_funnel_daily
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
FROM raw_ozon_posting_items i
LEFT JOIN raw_ozon_postings p
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
FROM raw_ozon_postings
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
FROM raw_ozon_stocks
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
FROM raw_ozon_ads_daily
WHERE day >= today() - {days}
"""


def _run_transform(days: int, task_name: str) -> dict[str, int | str]:
    run_id, started_at = new_run_context(task_name)
    client = get_ch_client()
    try:
        client.command(WB_SALES_TO_STG_SQL.format(days=days))
        client.command(WB_ORDERS_TO_STG_SQL.format(days=days))
        client.command(WB_STOCKS_TO_STG_SQL.format(days=days))
        client.command(WB_FUNNEL_TO_STG_SQL.format(days=days))
        client.command(OZON_SALES_TO_STG_SQL.format(days=days))
        client.command(OZON_ORDERS_TO_STG_SQL.format(days=days))
        client.command(OZON_STOCKS_TO_STG_SQL.format(days=days))
        client.command(OZON_ADS_TO_STG_SQL.format(days=max(days, 60)))
        log_task_run(client, task_name, run_id, started_at, "success", 0, f"transform done for {days} days")
        return {"status": "success", "days": days, "run_id": run_id}
    except Exception as exc:
        log_task_run(client, task_name, run_id, started_at, "failed", 0, str(exc))
        raise
    finally:
        client.close()


@shared_task(name="tasks.transforms.transform_all_recent")
def transform_all_recent() -> dict[str, int | str]:
    return _run_transform(days=14, task_name="tasks.transforms.transform_all_recent")


@shared_task(name="tasks.transforms.transform_backfill_days")
def transform_backfill_days(days: int = 14) -> dict[str, int | str]:
    safe_days = max(1, min(days, 365))
    return _run_transform(days=safe_days, task_name="tasks.transforms.transform_backfill_days")
