-- Whole daily snapshots also correctly replace a report whose rows were removed on refresh.
CREATE TABLE IF NOT EXISTS raw_ozon_buyouts_daily
(
  account_id LowCardinality(String),
  day Date,
  row_count UInt32,
  payload String,
  sha256 String,
  fetched_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (account_id, day);
