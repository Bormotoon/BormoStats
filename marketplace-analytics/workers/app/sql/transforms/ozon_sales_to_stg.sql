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
  p.created_at AS event_ts,
  'ozon' AS marketplace,
  i.account_id,
  i.posting_number AS order_id,
  i.posting_number,
  NULL AS srid,
  toString(i.ozon_product_id) AS product_id,
  NULL AS nm_id,
  i.ozon_product_id,
  i.offer_id,
  toInt32(i.quantity) AS qty,
  i.price AS price_gross,
  i.payout,
  0 AS is_return,
  p.created_at AS last_change_ts,
  i.payload AS meta_json,
  i.ingested_at
FROM
  (
    SELECT *
    FROM raw_ozon_posting_items FINAL
  ) i
LEFT JOIN
  (
    SELECT *
    FROM raw_ozon_postings FINAL
  ) p
  ON i.account_id = p.account_id
 AND i.posting_number = p.posting_number
WHERE i.ingested_at >= now() - toIntervalDay(%(days)s)
