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
  -- a day collected from /v1/finance/accrual/by-day replaces the legacy
  -- /v3/finance/transaction/list rows of that day, so nothing is counted twice
  AND (
    source = 'accrual_by_day'
    OR (account_id, toDate(operation_ts)) NOT IN (
      SELECT DISTINCT account_id, toDate(operation_ts)
      FROM raw_ozon_finance_ops
      WHERE source = 'accrual_by_day'
        AND operation_ts >= now() - toIntervalDay(%(days)s)
    )
  )
