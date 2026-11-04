CREATE TABLE IF NOT EXISTS raw_ozon_campaigns
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  campaign_id String,
  title String,
  state LowCardinality(String),
  adv_object_type LowCardinality(String),
  daily_budget Float64 DEFAULT 0,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, campaign_id);

