CREATE TABLE IF NOT EXISTS raw_ozon_realization_reports
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  month Date,
  row_number UInt32,
  ozon_product_id UInt64,
  offer_id String,
  seller_price Float64,
  sale_qty UInt32,
  sale_amount Float64,
  sale_commission Float64,
  return_qty UInt32,
  return_amount Float64,
  return_commission Float64,
  net_accrued Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(month)
ORDER BY (account_id, month, row_number, offer_id);

