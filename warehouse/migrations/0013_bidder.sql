-- Bidder: Ad campaigns and bid rules

CREATE TABLE IF NOT EXISTS dim_ad_campaign
(
  campaign_id String,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  title String,
  status LowCardinality(String),
  daily_budget Nullable(Float64),
  current_cpm Nullable(Float64),
  current_cpc Nullable(Float64),
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (marketplace, account_id, campaign_id);

CREATE TABLE IF NOT EXISTS dim_ad_rule
(
  rule_id String,
  campaign_id String,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  target_cpm Float64 DEFAULT 0,
  max_cpm Float64 DEFAULT 0,
  target_position UInt8 DEFAULT 0,
  is_active UInt8 DEFAULT 1,
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (marketplace, account_id, campaign_id, rule_id);
