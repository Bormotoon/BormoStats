-- Additive only: the original P&L mart and its pre-tax values are unchanged.
CREATE TABLE IF NOT EXISTS raw_ozon_realization_monthly
(
  account_id LowCardinality(String),
  month Date,
  sales_amount Decimal(18, 2),
  returns_amount Decimal(18, 2),
  row_count UInt32,
  source String DEFAULT '/v2/finance/realization',
  sha256 String,
  payload String,
  fetched_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (account_id, month);
