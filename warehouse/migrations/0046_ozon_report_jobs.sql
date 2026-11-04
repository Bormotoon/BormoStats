CREATE TABLE IF NOT EXISTS sys_ozon_report_jobs
(
  account_id LowCardinality(String),
  report_kind LowCardinality(String),
  period_key String,
  job_uuid String,
  status LowCardinality(String) DEFAULT 'pending',
  error String DEFAULT '',
  payload String DEFAULT '',
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (account_id, report_kind, period_key, job_uuid)
TTL created_at + INTERVAL 30 DAY;

