-- The latest stock day of each marketplace/account: one common max(day) would hide an
-- account whose collector is a day behind.
WITH scoped AS (
  SELECT day, marketplace, account_id, product_id, warehouse_id, stock_end
  FROM mrt_stock_daily FINAL
  WHERE (%(marketplace)s = '' OR marketplace = %(marketplace)s)
    AND (%(account_id)s = '' OR account_id = %(account_id)s)
    AND (marketplace, account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
),
names AS (
  SELECT marketplace, account_id, product_id, anyLast(title) AS name
  FROM dim_product FINAL
  WHERE title IS NOT NULL
  GROUP BY marketplace, account_id, product_id
),
latest AS (
  SELECT marketplace, account_id, max(day) AS current_day
  FROM scoped
  GROUP BY marketplace, account_id
)
SELECT
  s.day,
  s.marketplace,
  s.account_id,
  s.product_id,
  s.warehouse_id,
  any(n.name) AS title,
  sum(s.stock_end) AS stock_end
FROM scoped AS s
INNER JOIN latest AS l
  ON s.marketplace = l.marketplace
  AND s.account_id = l.account_id
  AND s.day = l.current_day
LEFT JOIN names AS n
  ON s.marketplace = n.marketplace
  AND s.account_id = n.account_id
  AND s.product_id = n.product_id
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
ORDER BY stock_end ASC, s.marketplace, s.product_id
LIMIT %(limit)s
OFFSET %(offset)s
