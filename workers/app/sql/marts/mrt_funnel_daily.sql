INSERT INTO mrt_funnel_daily
SELECT
  f.day,
  f.marketplace,
  f.account_id,
  f.product_id,
  sum(f.views) AS views,
  sum(f.adds_to_cart) AS adds_to_cart,
  sum(f.orders) AS orders,
  if(sum(f.views) = 0, 0, sum(f.orders) / sum(f.views)) AS cr_order,
  if(sum(f.views) = 0, 0, sum(f.adds_to_cart) / sum(f.views)) AS cr_cart,
  now() AS updated_at
FROM stg_funnel_daily f FINAL
WHERE f.day >= today() - %(days)s
GROUP BY f.day, f.marketplace, f.account_id, f.product_id
