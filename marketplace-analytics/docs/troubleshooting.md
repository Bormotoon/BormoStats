# Troubleshooting

## Backend `/ready` returns 503

- Check `clickhouse` and `redis` containers are healthy (`make ps`)
- Verify `.env` credentials (`CH_*`, `REDIS_URL`)
- Check ClickHouse ping: `curl http://localhost:18123/ping` (or `CH_HTTP_HOST_PORT` from `.env`)
- `/ready` now returns a sanitized `service not ready` error on purpose; inspect backend logs for
  the exact failing dependency (`service=clickhouse|redis`) and exception text

## Worker tasks are not running

- Check `worker` and `beat` container logs (`make logs`)
- Verify Celery can connect to Redis
- Ensure task names in beat schedule match task decorators
- Confirm healthchecks succeed:
  - backend: `curl http://localhost:18080/ready`
  - worker: `curl http://localhost:19101/metrics`
  - beat: `curl http://localhost:19102/metrics`

## Containers keep restarting or stay unhealthy

- Check `docker compose ps` and `make logs`
- Verify the configured guardrails in `.env`:
  - `*_MEMORY_LIMIT`
  - `*_MEMORY_RESERVATION`
  - `*_CPU_LIMIT`
- If the host is small, lower the limits for `metabase`, `worker`, or `clickhouse` and restart the stack
- Backend healthcheck uses `/ready`, so Redis/ClickHouse outages will mark the backend unhealthy

## No data in marts

- Trigger rebuilds via explicit admin actions:
  - `POST /api/v1/admin/transforms/recent`
  - `POST /api/v1/admin/marts/recent`
- Confirm raw tables have rows before transforms

## Frequent `429` / `5xx` from WB/Ozon

- Ensure workers are not over-concurrent for same source/account
- Review retry behavior in `collectors/common/http_client.py`
- Validate upstream API status and quotas before increasing schedule frequency
- Backfill after incident window:
  - `python3 scripts/backfill.py --marketplace wb --dataset sales --days 14 --api-key <KEY>`
  - `python3 scripts/backfill.py --marketplace ozon --dataset postings --days 14 --api-key <KEY>`

## Watermark looks stuck

- Inspect latest values in `/api/v1/admin/watermarks`
- Check corresponding task in `/api/v1/admin/task-runs`
- Verify source lock is not permanently held (`lock:{source}:{account_id}` in Redis)
- Run explicit backfill for affected dataset and account

## Rebuild marts for a period

- Trigger mart rebuild via admin API:
  - `POST /api/v1/admin/backfill` with `{"marketplace":"marts","dataset":"build","days":14}`
- Or via script:
  - `python3 scripts/backfill.py --marketplace marts --dataset build --days 14 --api-key <KEY>`

## Ozon capability / premium issues

- Check `sys_task_runs.meta_json` for entries with:
  - `{"capability":"ads","reason":"missing_perf_api_key"}`
  - `{"capability":"finance","reason":"unavailable_or_forbidden"}`
- Ensure optional features are configured:
  - `OZON_PERF_API_KEY` for ads
  - `OZON_POSTINGS_SCHEMAS=fbs,fbo` only if both schemes are applicable

## Telegram alerts are not sent

- Check `TG_BOT_TOKEN` and `TG_CHAT_ID` in `.env`
- Ensure `tasks.maintenance.run_automation_rules` is scheduled/executed

## Data quality task fails

- Inspect the latest `tasks.maintenance.run_data_quality_checks` entry in `/api/v1/admin/task-runs`
- Check `meta_json` for offending checks and sample rows
- Current checks cover stale marts, backward-moving watermarks, duplicate canonical grains, impossible timestamps, and negative/impossible aggregate values

## API auth failures for admin

- Use header `X-API-Key: <ADMIN_API_KEY>`
- Ensure backend uses same `.env` value
- The web UI does not persist the admin key in browser storage; paste it again after reload
- API responses are intentionally generic (`unauthorized` or `admin access unavailable`);
  check backend logs for `admin_request_rejected` and the exact `reason`
