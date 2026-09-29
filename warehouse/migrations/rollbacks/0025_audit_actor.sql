ALTER TABLE sys_audit_log DROP COLUMN IF EXISTS status_code;
ALTER TABLE sys_audit_log DROP COLUMN IF EXISTS request_id;
ALTER TABLE sys_audit_log DROP COLUMN IF EXISTS organization_id;
ALTER TABLE sys_audit_log DROP COLUMN IF EXISTS actor;
