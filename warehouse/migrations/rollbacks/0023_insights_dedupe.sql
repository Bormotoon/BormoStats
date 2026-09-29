ALTER TABLE dim_actionable_task DROP INDEX IF EXISTS idx_actionable_task_dedupe;
ALTER TABLE dim_actionable_task DROP COLUMN IF EXISTS dedupe_key;
