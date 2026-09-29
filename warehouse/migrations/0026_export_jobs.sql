-- Asynchronous CSV exports requested from the API and produced by workers.
CREATE TABLE IF NOT EXISTS sys_export_jobs
(
  export_id String,
  organization_id LowCardinality(String),
  requested_by String,
  dataset LowCardinality(String),
  params_json String,
  status LowCardinality(String),
  row_count UInt64 DEFAULT 0,
  file_name String DEFAULT '',
  error String DEFAULT '',
  created_at DateTime,
  updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, export_id)
TTL created_at + INTERVAL 30 DAY;
