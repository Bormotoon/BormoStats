INSERT INTO stg_finance_ops
(
  operation_ts,
  marketplace,
  account_id,
  operation_id,
  type,
  amount,
  currency,
  meta_json,
  ingested_at
)
SELECT
  operation_ts,
  'ozon' AS marketplace,
  account_id,
  operation_id,
  type,
  amount,
  currency,
  payload AS meta_json,
  ingested_at
FROM raw_ozon_finance_ops FINAL
WHERE operation_ts >= now() - toIntervalDay(%(days)s)
