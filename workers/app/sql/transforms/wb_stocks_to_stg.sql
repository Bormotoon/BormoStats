-- Stock per card (nm_id) and warehouse: sizes (chrt_id) are summed so stocks join sales,
-- which are per card. snapshot_ts is stored as UTC wall-clock (collectors write naive UTC),
-- so it is re-read as UTC to get the true instant and the Moscow day.
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
  'wb' AS marketplace,
  account_id,
  toString(nm_id) AS product_id,
  nm_id,
  NULL AS ozon_product_id,
  any(sku) AS offer_id,
  toInt64OrNull(toString(warehouse_id)) AS warehouse_id,
  toInt32(sum(amount)) AS amount,
  NULL AS reserved,
  NULL AS present,
  concat('[', arrayStringConcat(groupArray(payload), ','), ']') AS meta_json,
  max(ingested_at) AS ingested_at
FROM raw_wb_stocks FINAL
WHERE snapshot_ts >= now() - toIntervalDay(%(days)s + 2)
  AND nm_id IS NOT NULL
  AND toDate(toDateTime(toString(snapshot_ts), 'UTC'), 'Europe/Moscow')
      >= toDate(now(), 'Europe/Moscow') - %(days)s
GROUP BY snapshot_ts, account_id, nm_id, warehouse_id
