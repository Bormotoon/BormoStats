SELECT source, account_id, watermark_ts, updated_at
FROM sys_watermarks
ORDER BY source, account_id, updated_at DESC
LIMIT 500
