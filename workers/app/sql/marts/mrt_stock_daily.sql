-- Stock at the end of each Moscow day: the rows of the day's last snapshot per marketplace
-- and account. stg_stocks keeps the latest row per product and warehouse, so a product
-- that left a warehouse keeps an older row; matching the last snapshot drops it.
INSERT INTO mrt_stock_daily
SELECT
  s.day,
  s.marketplace,
  s.account_id,
  s.product_id,
  s.warehouse_id,
  sum(s.amount) AS stock_end,
  now() AS updated_at
FROM stg_stocks AS s FINAL
INNER JOIN
(
  SELECT day, marketplace, account_id, max(snapshot_ts) AS last_snapshot_ts
  FROM stg_stocks FINAL
  WHERE day >= toDate(now(), 'Europe/Moscow') - %(days)s
  GROUP BY day, marketplace, account_id
) AS l
  ON s.day = l.day
  AND s.marketplace = l.marketplace
  AND s.account_id = l.account_id
  AND s.snapshot_ts = l.last_snapshot_ts
WHERE s.day >= toDate(now(), 'Europe/Moscow') - %(days)s
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
