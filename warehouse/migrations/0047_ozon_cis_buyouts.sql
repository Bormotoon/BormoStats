CREATE TABLE IF NOT EXISTS raw_ozon_cis_buyouts
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  posting_number String,
  sku UInt64,
  offer_id String,
  product_name String DEFAULT '',
  quantity Int32,
  seller_price Float64,
  amount Float64,
  commission Float64 DEFAULT 0,
  payout Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, posting_number, sku);

