-- Actionable Insights: recommendation tasks

CREATE TABLE IF NOT EXISTS dim_actionable_task
(
  task_id String,
  organization_id LowCardinality(String),
  trigger_type LowCardinality(String),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id Nullable(String),
  campaign_id Nullable(String),
  title String,
  description String,
  priority LowCardinality(String),
  status LowCardinality(String) DEFAULT 'open',
  created_at DateTime DEFAULT now(),
  resolved_at Nullable(DateTime)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (organization_id, created_at, task_id);
