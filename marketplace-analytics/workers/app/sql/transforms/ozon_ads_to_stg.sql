INSERT INTO stg_ads_daily
(
  day,
  marketplace,
  account_id,
  campaign_id,
  impressions,
  clicks,
  cost,
  orders,
  revenue,
  meta_json,
  ingested_at
)
SELECT
  day,
  'ozon' AS marketplace,
  account_id,
  campaign_id,
  impressions,
  clicks,
  cost,
  orders,
  revenue,
  payload AS meta_json,
  ingested_at
FROM raw_ozon_ads_daily FINAL
WHERE day >= today() - %(days)s
