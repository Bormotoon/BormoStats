SELECT
  task_name,
  run_id,
  started_at,
  finished_at,
  status,
  rows_ingested,
  message,
  meta_json
FROM sys_task_runs
ORDER BY started_at DESC
LIMIT %(limit)s
