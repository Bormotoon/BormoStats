ALTER TABLE webhook_logs REMOVE TTL;
ALTER TABLE webhook_logs DROP COLUMN IF EXISTS next_retry_at;
ALTER TABLE webhook_logs DROP COLUMN IF EXISTS duration_ms;
ALTER TABLE webhook_logs DROP COLUMN IF EXISTS status;
ALTER TABLE webhook_logs DROP COLUMN IF EXISTS attempt;
ALTER TABLE webhook_logs DROP COLUMN IF EXISTS event_id;
