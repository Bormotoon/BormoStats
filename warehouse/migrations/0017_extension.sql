-- Browser Extension: SERP positions and competitor price tracking

CREATE TABLE IF NOT EXISTS raw_serp_positions
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  marketplace LowCardinality(String),
  keyword String,
  product_id UInt64,
  position UInt16,
  search_ts DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(search_ts)
ORDER BY (account_id, marketplace, keyword, product_id, search_ts);

CREATE TABLE IF NOT EXISTS mrt_keyword_positions_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  keyword String,
  product_id UInt64,
  avg_position Float64,
  min_position UInt16,
  max_position UInt16,
  checks_count UInt32,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, account_id, keyword, product_id);

CREATE TABLE IF NOT EXISTS raw_competitor_price_tracker
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  marketplace LowCardinality(String),
  competitor_product_id String,
  competitor_name String,
  price_rub Float64,
  price_with_discount_rub Nullable(Float64),
  in_stock UInt8,
  tracked_product_id Nullable(String),
  snapshot_ts DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (account_id, marketplace, competitor_product_id, snapshot_ts);
