INSERT INTO mrt_stock_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  warehouse_id,
  argMax(amount, snapshot_ts) AS stock_end,
  now() AS updated_at
FROM stg_stocks FINAL
WHERE day >= today() - %(days)s
GROUP BY day, marketplace, account_id, product_id, warehouse_id
