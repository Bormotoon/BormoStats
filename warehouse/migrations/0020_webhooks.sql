-- Webhooks & integrations — subscriptions and logs

CREATE TABLE IF NOT EXISTS webhook_subscriptions
(
  subscription_id String,
  organization_id LowCardinality(String),
  name String,
  endpoint_url String,
  secret String DEFAULT '',
  events Array(String) DEFAULT [],
  is_active UInt8 DEFAULT 1,
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, subscription_id);

CREATE TABLE IF NOT EXISTS webhook_logs
(
  log_id String,
  organization_id LowCardinality(String),
  subscription_id Nullable(String),
  event_type String,
  request_body String DEFAULT '',
  response_body String DEFAULT '',
  response_status UInt16 DEFAULT 0,
  success UInt8 DEFAULT 0,
  created_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (organization_id, created_at);
