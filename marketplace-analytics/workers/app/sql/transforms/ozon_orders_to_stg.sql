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
WHERE created_at >= now() - toIntervalDay(%(days)s)
