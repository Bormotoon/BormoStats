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
  'wb' AS marketplace,
  account_id,
  toString(nm_id) AS product_id,
  nm_id,
  chrt_id,
  any(barcode) AS sku,
  any(barcode) AS offer_id,
  NULL AS ozon_product_id,
  NULL AS title,
  NULL AS brand,
  NULL AS category,
  now() AS updated_at
FROM raw_wb_sales FINAL
WHERE event_ts >= now() - toIntervalDay(%(days)s)
GROUP BY account_id, nm_id, chrt_id
