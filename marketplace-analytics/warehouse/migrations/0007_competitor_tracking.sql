CREATE TABLE IF NOT EXISTS raw_competitor_products
(
  run_id String,
  marketplace LowCardinality(String),
  product_id UInt64,
  name String,
  brand String,
  category_id UInt64,
  category_name String,
  supplier_id UInt64,
  supplier_name String,
  rating Float32,
  review_count UInt32,
  payload String,
  updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(updated_at)
ORDER BY (marketplace, product_id);

CREATE TABLE IF NOT EXISTS raw_competitor_prices
(
  run_id String,
  marketplace LowCardinality(String),
  product_id UInt64,
  price_rub Float64,
  price_old_rub Float64,
  sale_percent UInt8,
  in_stock UInt32,
  snapshot_ts DateTime,
  payload String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (marketplace, product_id, snapshot_ts);

CREATE TABLE IF NOT EXISTS raw_competitor_search
(
  run_id String,
  marketplace LowCardinality(String),
  query String,
  search_page UInt32,
  position UInt32,
  product_id UInt64,
  price_rub Float64,
  snapshot_ts DateTime,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (marketplace, query, search_page, position);

CREATE TABLE IF NOT EXISTS mrt_competitor_daily
(
  day Date,
  marketplace LowCardinality(String),
  product_id UInt64,
  name String,
  brand String,
  category_name String,
  supplier_name String,
  rating Float32,
  review_count UInt32,
  price_rub Float64,
  price_old_rub Float64,
  sale_percent UInt8,
  in_stock UInt32
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, product_id);

CREATE TABLE IF NOT EXISTS mrt_competitor_category_daily
(
  day Date,
  marketplace LowCardinality(String),
  category_id UInt64,
  category_name String,
  tracked_products UInt32,
  supplier_count UInt32,
  brand_count UInt32,
  avg_rating Float32,
  min_price Float64,
  max_price Float64,
  avg_price Float64,
  total_stock UInt64
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, category_id);
