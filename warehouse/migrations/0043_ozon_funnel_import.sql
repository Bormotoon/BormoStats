CREATE TABLE IF NOT EXISTS ozon_funnel_import
(
  account_id LowCardinality(String), day Date, sku String, scheme LowCardinality(String),
  offer_id String, title String, position Float64, impressions UInt64,
  search_impressions UInt64, clicks UInt64, carts UInt64,
  imported_at DateTime64(6, 'UTC') DEFAULT now64(6)
)
ENGINE = ReplacingMergeTree(imported_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, sku, scheme);
