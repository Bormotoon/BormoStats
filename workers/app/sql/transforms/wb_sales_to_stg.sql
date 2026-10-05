-- One row per sold (qty > 0) or returned (qty < 0, is_return = 1) unit.
-- price_gross: seller's price after the seller's discount, positive; payout: amount due
-- for the unit before logistics, negative for a return.
-- WB reports Moscow wall-clock time without an offset, so the time is read from the
-- payload as Europe/Moscow (the raw event_ts column holds that wall clock as-is).
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
  event_msk AS event_ts,
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
  FROM raw_wb_sales FINAL
  -- coarse partition pruning; the exact window is the Moscow day below
  WHERE event_ts >= now() - toIntervalDay(%(days)s + 2)
)
WHERE toDate(event_msk, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
