WITH scoped AS (
  SELECT day, marketplace, account_id, product_id, warehouse_id, stock_end
  FROM mrt_stock_daily
  WHERE (%(marketplace)s = '' OR marketplace = %(marketplace)s)
    AND (%(account_id)s = '' OR account_id = %(account_id)s)
    AND (marketplace, account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
),
max_day AS (
  SELECT max(day) AS current_day
  FROM scoped
)
SELECT
  s.day,
  s.marketplace,
  s.account_id,
  s.product_id,
  s.warehouse_id,
  sum(s.stock_end) AS stock_end
FROM scoped AS s
CROSS JOIN max_day
WHERE s.day = max_day.current_day
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
ORDER BY stock_end ASC
LIMIT %(limit)s
OFFSET %(offset)s
