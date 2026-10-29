CREATE TABLE IF NOT EXISTS raw_ozon_ads_sku_daily
(
  account_id LowCardinality(String),
  day Date,
  campaign_id String,
  sku String,
  cost Decimal(18, 2),
  report_uuid String,
  fetched_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (account_id, day, campaign_id, sku);
