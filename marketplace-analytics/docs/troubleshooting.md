# Troubleshooting

## Backend `/ready` returns 503

- Check `clickhouse` and `redis` containers are healthy (`make ps`)
- Verify `.env` credentials (`CH_*`, `REDIS_URL`)

## Worker tasks are not running

- Check `worker` and `beat` container logs (`make logs`)
- Verify Celery can connect to Redis
- Ensure task names in beat schedule match task decorators

## No data in marts

- Trigger ingestion tasks manually via admin `/run-task`
- Run transform and mart tasks:
  - `tasks.transforms.transform_all_recent`
  - `tasks.marts.build_marts_recent`
- Confirm raw tables have rows before transforms

## Telegram alerts are not sent

- Check `TG_BOT_TOKEN` and `TG_CHAT_ID` in `.env`
- Ensure `tasks.maintenance.run_automation_rules` is scheduled/executed

## API auth failures for admin

- Use header `X-API-Key: <ADMIN_API_KEY>`
- Ensure backend uses same `.env` value
