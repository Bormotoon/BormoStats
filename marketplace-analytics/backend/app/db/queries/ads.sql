SELECT
  day,
  marketplace,
  account_id,
  campaign_id,
  sum(impressions) AS impressions,
  sum(clicks) AS clicks,
  sum(cost) AS cost,
  sum(orders) AS orders,
  sum(revenue) AS revenue,
  if(sum(revenue)=0, 0, sum(cost)/sum(revenue)) AS acos,
  if(sum(cost)=0, 0, (sum(revenue)-sum(cost))/sum(cost)) AS romi
FROM mrt_ads_daily
WHERE day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR account_id = %(account_id)s)
GROUP BY day, marketplace, account_id, campaign_id
ORDER BY day, campaign_id
LIMIT %(limit)s
