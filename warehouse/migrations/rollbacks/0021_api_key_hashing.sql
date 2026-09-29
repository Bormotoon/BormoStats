-- Plaintext keys cannot be restored; users must rotate keys after a rollback.
DROP TABLE IF EXISTS sys_api_key_usage;
ALTER TABLE dim_user DROP INDEX IF EXISTS idx_dim_user_api_key_id;
ALTER TABLE dim_user DROP COLUMN IF EXISTS api_key_revoked_at;
ALTER TABLE dim_user DROP COLUMN IF EXISTS api_key_expires_at;
ALTER TABLE dim_user DROP COLUMN IF EXISTS api_key_created_at;
ALTER TABLE dim_user DROP COLUMN IF EXISTS api_key_hash;
ALTER TABLE dim_user DROP COLUMN IF EXISTS api_key_id;
