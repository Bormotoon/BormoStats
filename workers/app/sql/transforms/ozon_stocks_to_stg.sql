-- Available stock (present - reserved) per SKU and warehouse. snapshot_ts is stored as UTC
-- wall-clock (see wb_stocks_to_stg.sql).
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
  toDateTime(toString(snapshot_ts), 'UTC') AS snapshot_ts,
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
WHERE snapshot_ts >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(toDateTime(toString(snapshot_ts), 'UTC'), 'Europe/Moscow')
      >= toDate(now(), 'Europe/Moscow') - %(days)s
