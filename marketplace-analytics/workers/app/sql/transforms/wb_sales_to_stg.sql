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
WHERE event_ts >= now() - toIntervalDay(%(days)s)
