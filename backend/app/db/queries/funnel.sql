WITH names AS (
  SELECT
    marketplace, account_id, product_id,
    anyLast(title) AS name, anyLast(offer_id) AS article, anyLast(image_url) AS image
  FROM dim_product FINAL
  WHERE title IS NOT NULL
  GROUP BY marketplace, account_id, product_id
)
SELECT
  f.day AS day,
  f.marketplace AS marketplace,
  f.account_id AS account_id,
  f.product_id AS product_id,
  any(n.name) AS title,
  any(n.article) AS offer_id,
  any(n.image) AS image_url,
  sum(f.views) AS views,
  sum(f.adds_to_cart) AS adds_to_cart,
  sum(f.orders) AS orders,
  if(sum(f.views)=0, 0, sum(f.orders)/sum(f.views)) AS cr_order,
  if(sum(f.views)=0, 0, sum(f.adds_to_cart)/sum(f.views)) AS cr_cart
FROM mrt_funnel_daily AS f FINAL
LEFT JOIN names AS n
  ON f.marketplace = n.marketplace
  AND f.account_id = n.account_id
  AND f.product_id = n.product_id
WHERE f.day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR f.marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR f.account_id = %(account_id)s)
  AND (f.marketplace, f.account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
GROUP BY f.day, f.marketplace, f.account_id, f.product_id
ORDER BY f.day, f.product_id
LIMIT %(limit)s
OFFSET %(offset)s
