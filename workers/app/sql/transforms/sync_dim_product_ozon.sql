INSERT INTO dim_product
(
  marketplace,
  account_id,
  product_id,
  nm_id,
  chrt_id,
  sku,
  offer_id,
  ozon_product_id,
  title,
  brand,
  category,
  updated_at
)
SELECT
  'ozon' AS marketplace,
  i.account_id,
  toString(i.ozon_product_id) AS product_id,
  NULL AS nm_id,
  NULL AS chrt_id,
  any(i.offer_id) AS sku,
  any(i.offer_id) AS offer_id,
  i.ozon_product_id,
  any(i.name) AS title,
  NULL AS brand,
  NULL AS category,
  now() AS updated_at
FROM
  (
    SELECT *
    FROM raw_ozon_posting_items FINAL
  ) i
WHERE i.ingested_at >= now() - toIntervalDay(%(days)s)
GROUP BY i.account_id, i.ozon_product_id
