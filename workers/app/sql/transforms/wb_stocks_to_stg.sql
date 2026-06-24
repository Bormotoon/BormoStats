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
WHERE snapshot_ts >= now() - toIntervalDay(%(days)s)
