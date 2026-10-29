-- The latest stock day of each marketplace/account: one common max(day) would hide an
-- account whose collector is a day behind.
WITH scoped AS (
  SELECT day, marketplace, account_id, product_id, warehouse_id, stock_end
  FROM mrt_stock_daily FINAL
  WHERE (%(marketplace)s = '' OR marketplace = %(marketplace)s)
    AND day <= %(as_of)s
    AND (%(account_id)s = '' OR account_id = %(account_id)s)
    AND (marketplace, account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
),
names AS (
  SELECT
    marketplace, account_id, product_id,
    anyLast(title) AS name, anyLast(offer_id) AS article, anyLast(image_url) AS image
  FROM dim_product FINAL
  WHERE title IS NOT NULL
  GROUP BY marketplace, account_id, product_id
),
-- warehouse names come only in the snapshots' payloads (one item per row)
warehouses AS (
  SELECT 'ozon' AS marketplace, account_id, warehouse_id,
    argMax(JSONExtractString(payload, 1, 'warehouse_name'), snapshot_ts) AS warehouse_name
  FROM raw_ozon_stocks
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY AND warehouse_id IS NOT NULL
  GROUP BY account_id, warehouse_id
  UNION ALL
  SELECT 'wb' AS marketplace, account_id, toInt64(warehouse_id) AS warehouse_id,
    argMax(JSONExtractString(payload, 1, 'warehouseName'), snapshot_ts) AS warehouse_name
  FROM raw_wb_stocks
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY AND warehouse_id IS NOT NULL
  GROUP BY account_id, warehouse_id
),
latest AS (
  SELECT marketplace, account_id, max(day) AS current_day
  FROM scoped
  GROUP BY marketplace, account_id
)
SELECT
  s.day AS day,
  s.marketplace AS marketplace,
  s.account_id AS account_id,
  s.product_id AS product_id,
  s.warehouse_id AS warehouse_id,
  -- WB's stock report is one total over its warehouses, without an id
  multiIf(
    any(w.warehouse_name) != '', any(w.warehouse_name),
    s.warehouse_id IS NULL AND s.marketplace = 'wb', 'Склад WB',
    s.warehouse_id IS NULL, '',
    toString(s.warehouse_id)
  ) AS warehouse_name,
  any(n.name) AS title,
  any(n.article) AS offer_id,
  any(n.image) AS image_url,
  sum(s.stock_end) AS stock_end,
  if(any(oc.cost_price_rub) > 0, any(oc.cost_price_rub),
    if(any(c.cost_price_rub) > 0, any(c.cost_price_rub), NULL)) AS cost_price_rub,
  stock_end * cost_price_rub AS stock_cost_rub
FROM scoped AS s
INNER JOIN latest AS l
  ON s.marketplace = l.marketplace
  AND s.account_id = l.account_id
  AND s.day = l.current_day
LEFT JOIN names AS n
  ON s.marketplace = n.marketplace
  AND s.account_id = n.account_id
  AND s.product_id = n.product_id
LEFT JOIN warehouses AS w
  ON s.marketplace = w.marketplace
  AND s.account_id = w.account_id
  AND ifNull(s.warehouse_id, -1) = w.warehouse_id
LEFT JOIN v_offer_cost AS oc
  ON s.marketplace = oc.marketplace
  AND s.account_id = oc.account_id
  AND s.product_id = oc.product_id
LEFT JOIN dim_product_cost AS c FINAL
  ON s.marketplace = c.marketplace
  AND s.product_id = toString(c.product_id)
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
ORDER BY stock_end ASC, s.marketplace, s.product_id
LIMIT %(limit)s
OFFSET %(offset)s
