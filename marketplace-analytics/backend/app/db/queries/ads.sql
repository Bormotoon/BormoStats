SELECT
  a.day,
  a.marketplace,
  a.account_id,
  a.campaign_id,
  sum(a.impressions) AS impressions,
  sum(a.clicks) AS clicks,
  sum(a.cost) AS cost,
  sum(a.orders) AS orders,
  sum(a.revenue) AS revenue,
  if(sum(a.revenue)=0, 0, sum(a.cost)/sum(a.revenue)) AS acos,
  if(sum(a.cost)=0, 0, (sum(a.revenue)-sum(a.cost))/sum(a.cost)) AS romi
FROM mrt_ads_daily AS a
WHERE a.day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR a.marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR a.account_id = %(account_id)s)
GROUP BY a.day, a.marketplace, a.account_id, a.campaign_id
ORDER BY a.day, a.campaign_id
LIMIT %(limit)s
OFFSET %(offset)s
