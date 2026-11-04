WITH scoped AS (
  SELECT day, marketplace, account_id, product_id, warehouse_id, stock_end
  FROM mrt_stock_daily FINAL
  WHERE day <= %(as_of)s
    AND (%(marketplace)s = '' OR marketplace = %(marketplace)s)
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
costs AS (
  SELECT marketplace, account_id, product_id, any(cost_price_rub) AS cost_price_rub
  FROM v_offer_cost
  GROUP BY marketplace, account_id, product_id
),
legacy_costs AS (
  SELECT marketplace, toString(product_id) AS product_id, any(cost_price_rub) AS cost_price_rub
  FROM dim_product_cost FINAL
  GROUP BY marketplace, product_id
),
warehouses AS (
  SELECT 'ozon' AS marketplace, account_id, warehouse_id,
    argMax(JSONExtractString(payload, 1, 'warehouse_name'), snapshot_ts) AS warehouse_name
  FROM raw_ozon_stocks FINAL
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY AND warehouse_id IS NOT NULL
  GROUP BY account_id, warehouse_id
  UNION ALL
  SELECT 'wb' AS marketplace, account_id, toInt64(warehouse_id) AS warehouse_id,
    argMax(JSONExtractString(payload, 1, 'warehouseName'), snapshot_ts) AS warehouse_name
  FROM raw_wb_stocks FINAL
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY AND warehouse_id IS NOT NULL
  GROUP BY account_id, warehouse_id
  UNION ALL
  SELECT 'ym' AS marketplace, account_id, warehouse_id,
    argMax(warehouse_name, snapshot_ts) AS warehouse_name
  FROM raw_ym_stocks FINAL
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY
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
  multiIf(
    any(w.warehouse_name) != '', any(w.warehouse_name),
    s.warehouse_id IS NULL AND s.marketplace = 'wb', 'Склад WB',
    s.warehouse_id IS NULL AND s.marketplace = 'ym', 'Склад Я.Маркет',
    s.warehouse_id IS NULL, '',
    toString(s.warehouse_id)
  ) AS warehouse_name,
  any(n.name) AS title,
  any(n.article) AS offer_id,
  any(n.image) AS image_url,
  sum(s.stock_end) AS stock_end,
  if(any(c.cost_price_rub) > 0, any(c.cost_price_rub),
     if(any(lc.cost_price_rub) > 0, any(lc.cost_price_rub), NULL)) AS cost_price_rub,
  if(cost_price_rub IS NOT NULL, round(sum(s.stock_end) * cost_price_rub, 2), NULL) AS stock_value_rub
FROM scoped AS s
INNER JOIN latest AS l
  ON s.marketplace = l.marketplace
  AND s.account_id = l.account_id
  AND s.day = l.current_day
LEFT JOIN names AS n
  ON s.marketplace = n.marketplace
  AND s.account_id = n.account_id
  AND s.product_id = n.product_id
LEFT JOIN costs AS c
  ON s.marketplace = c.marketplace
  AND s.account_id = c.account_id
  AND s.product_id = c.product_id
LEFT JOIN legacy_costs AS lc
  ON s.marketplace = lc.marketplace
  AND s.product_id = lc.product_id
LEFT JOIN warehouses AS w
  ON s.marketplace = w.marketplace
  AND s.account_id = w.account_id
  AND ifNull(s.warehouse_id, -1) = w.warehouse_id
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
ORDER BY stock_end ASC, s.marketplace, s.product_id
LIMIT %(limit)s
OFFSET %(offset)s
