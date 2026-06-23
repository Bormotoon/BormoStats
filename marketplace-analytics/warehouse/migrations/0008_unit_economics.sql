CREATE TABLE IF NOT EXISTS dim_product_cost
(
  marketplace LowCardinality(String),
  product_id UInt64,
  cost_price_rub Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY (marketplace)
ORDER BY (marketplace, product_id);

CREATE TABLE IF NOT EXISTS mrt_profit_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id String,
  product_id UInt64,
  nm_id Nullable(UInt64),
  ozon_product_id Nullable(UInt64),
  product_name String,
  revenue_rub Float64,
  payout_rub Float64,
  cost_price_rub Float64,
  total_cost_rub Float64,
  profit_rub Float64,
  margin_pct Float32,
  quantity UInt32,
  return_qty UInt32
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, account_id, product_id);
