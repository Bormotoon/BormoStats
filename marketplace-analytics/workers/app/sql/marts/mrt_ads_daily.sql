INSERT INTO mrt_ads_daily
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
  if(sum(a.revenue) = 0, 0, sum(a.cost) / sum(a.revenue)) AS acos,
  if(sum(a.cost) = 0, 0, (sum(a.revenue) - sum(a.cost)) / sum(a.cost)) AS romi,
  now() AS updated_at
FROM stg_ads_daily a FINAL
WHERE a.day >= today() - %(days)s
GROUP BY a.day, a.marketplace, a.account_id, a.campaign_id
