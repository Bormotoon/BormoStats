-- One row per ordered unit; price_gross is the seller's price after the seller's discount.
-- Times are Moscow wall-clock in the payload (see wb_sales_to_stg.sql).
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
  event_msk AS event_ts,
  'wb' AS marketplace,
  account_id,
  srid AS order_id,
  if(JSONExtractBool(payload, 'isCancel'), 'cancelled', 'new') AS status,
  toString(nm_id) AS product_id,
  toInt32(quantity) AS qty,
  price_rub AS price_gross,
  parseDateTimeBestEffortOrNull(JSONExtractString(payload, 'lastChangeDate'), 'Europe/Moscow') AS last_change_ts,
  payload AS meta_json,
  ingested_at
FROM
(
  SELECT
    *,
    coalesce(
      parseDateTimeBestEffortOrNull(JSONExtractString(payload, 'date'), 'Europe/Moscow'),
      toDateTime(toString(event_ts), 'Europe/Moscow')
    ) AS event_msk
  FROM raw_wb_orders FINAL
  WHERE event_ts >= now() - toIntervalDay(%(days)s + 2)
)
WHERE toDate(event_msk, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
