-- Webhook delivery engine: per-attempt log with status, retries and dead-letter marking.
-- webhook_subscriptions.secret now holds AES-GCM ciphertext (see common/secret_box.py);
-- pre-existing plaintext secrets are cleared and must be rotated via the API.
ALTER TABLE webhook_subscriptions UPDATE secret = '' WHERE secret != '' AND NOT startsWith(secret, 'v1:')
  SETTINGS mutations_sync = 2;

ALTER TABLE webhook_logs ADD COLUMN IF NOT EXISTS event_id String DEFAULT '';
ALTER TABLE webhook_logs ADD COLUMN IF NOT EXISTS attempt UInt8 DEFAULT 1;
ALTER TABLE webhook_logs ADD COLUMN IF NOT EXISTS status LowCardinality(String) DEFAULT '';
ALTER TABLE webhook_logs ADD COLUMN IF NOT EXISTS duration_ms UInt32 DEFAULT 0;
ALTER TABLE webhook_logs ADD COLUMN IF NOT EXISTS next_retry_at Nullable(DateTime);
ALTER TABLE webhook_logs MODIFY TTL created_at + INTERVAL 90 DAY;
