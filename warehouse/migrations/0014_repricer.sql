-- Repricer: Price rules and break-even analysis

CREATE TABLE IF NOT EXISTS dim_price_rule
(
  rule_id String,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  min_price Float64 DEFAULT 0,
  max_price Float64 DEFAULT 0,
  target_margin_percent Float64 DEFAULT 0,
  is_active UInt8 DEFAULT 1,
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (marketplace, account_id, product_id, rule_id);

CREATE TABLE IF NOT EXISTS mrt_breakeven_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  current_price Float64,
  cost_price Float64,
  commission_pct Float32,
  logistics_rub Float64,
  breakeven_price Float64,
  min_recommended_price Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, account_id, product_id);
