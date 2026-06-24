CREATE TABLE IF NOT EXISTS dim_user
(
  user_id String,
  name String,
  email String,
  api_key String,
  role Enum8('admin' = 1, 'analyst' = 2),
  is_active UInt8 DEFAULT 1,
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id);

SET create_index_ignore_unique = 1;
CREATE INDEX IF NOT EXISTS idx_dim_user_api_key ON dim_user (api_key) TYPE bloom_filter GRANULARITY 1;
