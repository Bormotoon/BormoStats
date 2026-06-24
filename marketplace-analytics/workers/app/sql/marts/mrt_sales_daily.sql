INSERT INTO mrt_sales_daily
SELECT
  s.day,
  s.marketplace,
  s.account_id,
  s.product_id,
  sum(s.qty) AS qty,
  sumIf(s.price_gross * s.qty, s.is_return = 0) AS revenue,
  sum(s.payout) AS payout,
  sumIf(s.qty, s.is_return = 1) AS returns_qty,
  now() AS updated_at
FROM stg_sales s FINAL
WHERE s.day >= today() - %(days)s
GROUP BY s.day, s.marketplace, s.account_id, s.product_id
