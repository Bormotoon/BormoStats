WITH max_day AS (
  SELECT max(day) AS current_day
  FROM mrt_stock_daily
)
SELECT
  s.day,
  s.marketplace,
  s.account_id,
  s.product_id,
  s.warehouse_id,
  sum(s.stock_end) AS stock_end
FROM mrt_stock_daily AS s
CROSS JOIN max_day
WHERE s.day = max_day.current_day
  AND (%(marketplace)s = '' OR s.marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR s.account_id = %(account_id)s)
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
ORDER BY stock_end ASC
LIMIT %(limit)s
