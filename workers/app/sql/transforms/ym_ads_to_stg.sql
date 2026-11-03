INSERT INTO stg_ads_daily
(day, marketplace, account_id, campaign_id, impressions, clicks, cost, orders, revenue, meta_json, ingested_at)
SELECT day, 'ym', account_id, campaign_id, sum(impressions), sum(clicks), sum(cost), sum(orders),
  sum(revenue), '', max(ingested_at)
FROM raw_ym_ads FINAL
WHERE day >= toDate(now(), 'Europe/Moscow') - %(days)s
GROUP BY day, account_id, campaign_id;
