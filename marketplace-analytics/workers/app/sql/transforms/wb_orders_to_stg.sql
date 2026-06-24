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
WHERE event_ts >= now() - toIntervalDay(%(days)s)
