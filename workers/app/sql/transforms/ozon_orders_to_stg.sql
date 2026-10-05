-- One row per posting. created_at comes from the payload (UTC with an offset) so the
-- event time is a true instant and the day is the Moscow day of the order.
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
  created AS event_ts,
  'ozon' AS marketplace,
  account_id,
  posting_number AS order_id,
  status,
  NULL AS product_id,
  NULL AS qty,
  NULL AS price_gross,
  parseDateTimeBestEffortOrNull(JSONExtractString(payload, 'in_process_at')) AS last_change_ts,
  payload AS meta_json,
  ingested_at
FROM
(
  SELECT
    *,
    coalesce(
      parseDateTimeBestEffortOrNull(JSONExtractString(payload, 'created_at')),
      toDateTime(toString(created_at), 'UTC')
    ) AS created
  FROM raw_ozon_postings FINAL
  WHERE created_at >= now() - toIntervalDay(%(days)s + 2)
)
WHERE toDate(created, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
