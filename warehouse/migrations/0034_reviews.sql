-- Reviews: buyers' reviews of the shop's products, the replies sent from BormoStats, the
-- auto-reply settings and the reply templates (backend/app/services/review_service.py,
-- workers/app/tasks/reviews.py).

-- A review as the marketplace last returned it. product_id is the WB nmID or the Ozon SKU.
-- has_text is 0 for a rating without any text (WB: no text, pros and cons).
CREATE TABLE IF NOT EXISTS fct_review
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  review_id String,
  product_id String,
  offer_id String DEFAULT '',
  product_name String DEFAULT '',
  rating UInt8,
  text String DEFAULT '',
  pros String DEFAULT '',
  cons String DEFAULT '',
  has_text UInt8,
  user_name String DEFAULT '',
  photos UInt16 DEFAULT 0,
  created_at DateTime,
  is_answered UInt8,
  answer_text String DEFAULT '',
  payload String DEFAULT '',
  synced_at DateTime
)
ENGINE = ReplacingMergeTree(synced_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (marketplace, account_id, review_id);

-- Every reply BormoStats sent or tried to send. source: auto_template, auto_ai or manual;
-- status: sent or failed (response kept in error).
CREATE TABLE IF NOT EXISTS sys_review_reply
(
  reply_id String,
  organization_id LowCardinality(String),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  review_id String,
  text String,
  source LowCardinality(String),
  status LowCardinality(String),
  error String DEFAULT '',
  created_by String DEFAULT '',
  created_at DateTime
)
ENGINE = MergeTree
ORDER BY (marketplace, account_id, review_id, created_at);

-- Auto replies of an organization to reviews without text: off, template or ai per rating.
CREATE TABLE IF NOT EXISTS dim_review_settings
(
  organization_id LowCardinality(String),
  auto_enabled UInt8 DEFAULT 0,
  mode_1 LowCardinality(String) DEFAULT 'off',
  mode_2 LowCardinality(String) DEFAULT 'off',
  mode_3 LowCardinality(String) DEFAULT 'off',
  mode_4 LowCardinality(String) DEFAULT 'off',
  mode_5 LowCardinality(String) DEFAULT 'off',
  updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY organization_id;

-- Reply templates per rating, for reviews without text (kind no_text) and with it (text).
CREATE TABLE IF NOT EXISTS dim_review_template
(
  organization_id LowCardinality(String),
  template_id String,
  kind LowCardinality(String),
  rating UInt8,
  text String,
  is_deleted UInt8 DEFAULT 0,
  updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, template_id);

-- The outcome of the last review sync of each account: ok, unavailable (no access to the
-- method, e.g. Ozon without Premium Plus), error or no_credentials.
CREATE TABLE IF NOT EXISTS sys_review_sync
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  status LowCardinality(String),
  message String DEFAULT '',
  unanswered UInt32 DEFAULT 0,
  synced_at DateTime
)
ENGINE = ReplacingMergeTree(synced_at)
ORDER BY (marketplace, account_id);
