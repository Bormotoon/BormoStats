SELECT
  day,
  marketplace,
  account_id,
  product_id,
  sum(qty) AS qty,
  sum(revenue) AS revenue,
  sum(returns_qty) AS returns_qty,
  sum(ifNull(payout, 0)) AS payout
FROM mrt_sales_daily
WHERE day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR account_id = %(account_id)s)
GROUP BY day, marketplace, account_id, product_id
ORDER BY day, revenue DESC
LIMIT %(limit)s
