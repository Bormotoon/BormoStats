CREATE TABLE IF NOT EXISTS mrt_ad_performance_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id String,
  campaign_id String,
  impressions UInt64,
  clicks UInt64,
  cost_rub Float64,
  orders UInt64,
  revenue_rub Float64,
  drr_pct Float32,
  roas Float32,
  acos_pct Float32,
  cpc_rub Float32,
  cpm_rub Float32,
  conversion_pct Float32
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, account_id, campaign_id);
