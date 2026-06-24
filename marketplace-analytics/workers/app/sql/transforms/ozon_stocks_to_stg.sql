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
WHERE snapshot_ts >= now() - toIntervalDay(%(days)s)
