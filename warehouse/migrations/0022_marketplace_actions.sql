-- Bidder/repricer: dry-run by default and an audit trail of every bid/price change.
ALTER TABLE dim_ad_rule ADD COLUMN IF NOT EXISTS dry_run UInt8 DEFAULT 1;
-- WB sets bids per product (nm_id) and placement inside a campaign.
ALTER TABLE dim_ad_rule ADD COLUMN IF NOT EXISTS product_id String DEFAULT '';
ALTER TABLE dim_ad_rule ADD COLUMN IF NOT EXISTS placement LowCardinality(String) DEFAULT 'combined';
ALTER TABLE dim_price_rule ADD COLUMN IF NOT EXISTS dry_run UInt8 DEFAULT 1;

CREATE TABLE IF NOT EXISTS sys_marketplace_actions
(
  action_id String,
  organization_id LowCardinality(String),
  source LowCardinality(String),
  rule_id String,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  target_type LowCardinality(String),
  target_id String,
  before_value Nullable(Float64),
  after_value Float64,
  dry_run UInt8,
  status LowCardinality(String),
  response_status UInt16 DEFAULT 0,
  response_body String DEFAULT '',
  idempotency_key String,
  created_at DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (organization_id, source, created_at, action_id)
TTL created_at + INTERVAL 365 DAY;
