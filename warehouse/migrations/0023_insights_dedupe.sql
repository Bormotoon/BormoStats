-- Insights: logical dedupe key so repeated generator runs do not duplicate open tasks.
ALTER TABLE dim_actionable_task ADD COLUMN IF NOT EXISTS dedupe_key String DEFAULT '';
ALTER TABLE dim_actionable_task ADD INDEX IF NOT EXISTS idx_actionable_task_dedupe dedupe_key TYPE bloom_filter GRANULARITY 1;
