CREATE TABLE IF NOT EXISTS raw_ozon_sku_ad_reports
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  campaign_id String,
  sku UInt64,
  offer_id String DEFAULT '',
  title String DEFAULT '',
  impressions UInt64 DEFAULT 0,
  clicks UInt64 DEFAULT 0,
  cost Float64,
  orders UInt64 DEFAULT 0,
  revenue Float64 DEFAULT 0,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, campaign_id, sku);

