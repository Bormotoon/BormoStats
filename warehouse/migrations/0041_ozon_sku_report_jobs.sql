CREATE TABLE IF NOT EXISTS raw_ozon_sku_report_jobs
(
  cache_key String,
  account_id String,
  date_from Date,
  date_to Date,
  campaigns String,
  report_uuid String,
  payload String,
  updated_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY cache_key;
