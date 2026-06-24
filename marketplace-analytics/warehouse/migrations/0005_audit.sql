CREATE TABLE IF NOT EXISTS sys_audit_log
(
  event_ts DateTime DEFAULT now(),
  event LowCardinality(String),
  action LowCardinality(String),
  path String,
  method LowCardinality(String),
  remote_addr String,
  forwarded_for Nullable(String),
  user_agent Nullable(String),
  details_json String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_ts)
ORDER BY (event_ts, action);
