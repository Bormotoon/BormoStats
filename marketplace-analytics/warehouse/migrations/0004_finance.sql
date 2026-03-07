CREATE TABLE IF NOT EXISTS stg_finance_ops
(
  operation_ts DateTime,
  day Date MATERIALIZED toDate(operation_ts),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  operation_id String,
  type LowCardinality(String),
  amount Float64,
  currency LowCardinality(String),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, operation_id, operation_ts);
