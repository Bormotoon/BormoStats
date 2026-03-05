SELECT
  day,
  marketplace,
  account_id,
  product_id,
  sum(views) AS views,
  sum(adds_to_cart) AS adds_to_cart,
  sum(orders) AS orders,
  if(sum(views)=0, 0, sum(orders)/sum(views)) AS cr_order,
  if(sum(views)=0, 0, sum(adds_to_cart)/sum(views)) AS cr_cart
FROM mrt_funnel_daily
WHERE day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR account_id = %(account_id)s)
GROUP BY day, marketplace, account_id, product_id
ORDER BY day, product_id
LIMIT %(limit)s
