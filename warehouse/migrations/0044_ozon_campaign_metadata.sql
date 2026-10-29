CREATE TABLE IF NOT EXISTS raw_ozon_campaign_metadata
(
  account_id LowCardinality(String),
  campaign_id String,
  effective_from DateTime('UTC'),
  payload String,
  fetched_at DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (account_id, campaign_id, effective_from);
