SELECT
  f.day,
  f.marketplace,
  f.account_id,
  f.product_id,
  sum(f.views) AS views,
  sum(f.adds_to_cart) AS adds_to_cart,
  sum(f.orders) AS orders,
  if(sum(f.views)=0, 0, sum(f.orders)/sum(f.views)) AS cr_order,
  if(sum(f.views)=0, 0, sum(f.adds_to_cart)/sum(f.views)) AS cr_cart
FROM mrt_funnel_daily AS f
WHERE f.day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR f.marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR f.account_id = %(account_id)s)
GROUP BY f.day, f.marketplace, f.account_id, f.product_id
ORDER BY f.day, f.product_id
LIMIT %(limit)s
