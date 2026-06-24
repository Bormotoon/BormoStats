CREATE TABLE IF NOT EXISTS mrt_supply_planning_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id String,
  product_id UInt64,
  product_name String,
  avg_sales_7d Float64,
  avg_sales_14d Float64,
  avg_sales_30d Float64,
  latest_stock Int32,
  days_until_stockout Float64,
  reorder_qty UInt32,
  is_critical UInt8
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, account_id, product_id);
