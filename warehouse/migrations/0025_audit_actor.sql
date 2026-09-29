-- Audit log: who did what, in which organization, correlated by request id.
ALTER TABLE sys_audit_log ADD COLUMN IF NOT EXISTS actor String DEFAULT '';
ALTER TABLE sys_audit_log ADD COLUMN IF NOT EXISTS organization_id LowCardinality(String) DEFAULT '';
ALTER TABLE sys_audit_log ADD COLUMN IF NOT EXISTS request_id String DEFAULT '';
ALTER TABLE sys_audit_log ADD COLUMN IF NOT EXISTS status_code UInt16 DEFAULT 0;
