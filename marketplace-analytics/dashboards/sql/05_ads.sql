SELECT day, campaign_id, cost, revenue, acos, romi
FROM mrt_ads_daily
WHERE day BETWEEN {{from}} AND {{to}}
ORDER BY day, campaign_id;
