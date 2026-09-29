-- API keys: store only a lookup id and a hash, never the plaintext key.
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS api_key_id String DEFAULT '';
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS api_key_hash String DEFAULT '';
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS api_key_created_at Nullable(DateTime);
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS api_key_expires_at Nullable(DateTime);
ALTER TABLE dim_user ADD COLUMN IF NOT EXISTS api_key_revoked_at Nullable(DateTime);

-- Existing plaintext keys become SHA-256 digests (upgraded to salted scrypt on first use).
-- The lookup id mirrors app.core.security.legacy_key_id().
ALTER TABLE dim_user
  UPDATE
    api_key_id = concat('legacy_', substring(lower(hex(SHA256(api_key))), 1, 24)),
    api_key_hash = concat('sha256$', lower(hex(SHA256(api_key)))),
    api_key_created_at = updated_at,
    api_key = ''
  WHERE api_key != '' AND api_key_hash = ''
  SETTINGS mutations_sync = 2;

ALTER TABLE dim_user DROP INDEX IF EXISTS idx_dim_user_api_key;
ALTER TABLE dim_user ADD INDEX IF NOT EXISTS idx_dim_user_api_key_id api_key_id TYPE bloom_filter GRANULARITY 1;

CREATE TABLE IF NOT EXISTS sys_api_key_usage
(
  api_key_id String,
  user_id String,
  last_used_at DateTime
)
ENGINE = ReplacingMergeTree(last_used_at)
ORDER BY (api_key_id);
