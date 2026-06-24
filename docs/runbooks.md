# Runbooks

This document is the operator-facing recovery guide for the most common production incidents.
Use `docs/troubleshooting.md` as a fast index, then follow the matching runbook here.

## Stalled watermark

Symptoms:

- `MarketplaceWatermarkStale` alert is firing
- `/api/v1/admin/watermarks` stops advancing for one source/account
- Recent marts stop changing even though the marketplaces still have activity

Diagnosis:

1. Inspect `/api/v1/admin/watermarks` and note the stale `source` + `account_id`.
2. Inspect `/api/v1/admin/task-runs` for the same source and time window.
3. Check backend/worker logs for the source and account:
   - `make logs`
   - search for `task_name`, `account_id`, `source`, `lock_conflict`, `429`, `5xx`
4. If the source is blocked by a renewable Redis lock, inspect the key:
   - `docker compose exec redis redis-cli GET lock:<source>:<account_id>`
5. Confirm upstream credentials and quotas are still valid with `make check-tokens`.

Recovery:

1. If the upstream was temporarily unavailable, wait for the incident to stop and do not raise concurrency.
2. Requeue the affected window with the admin API or `scripts/backfill.py`, for example:
   - `python3 scripts/backfill.py --marketplace wb --dataset sales --days 14 --api-key <KEY>`
   - `python3 scripts/backfill.py --marketplace ozon --dataset postings --days 14 --api-key <KEY>`
3. If transforms or marts are behind, run:
   - `curl -X POST http://localhost:18080/api/v1/admin/transforms/recent -H 'X-API-Key: <KEY>'`
   - `curl -X POST http://localhost:18080/api/v1/admin/marts/recent -H 'X-API-Key: <KEY>'`
4. Re-check `/api/v1/admin/watermarks` until the watermark advances.
5. Confirm the latest `sys_task_runs` rows are `success`.

Exit criteria:

- stale alert clears
- watermark advances again
- marts reflect the missed period

## Redis issues

Symptoms:

- `/ready` returns `503` and backend logs `service=redis`
- `RedisUnavailable` or `RedisMemorySaturation` alert is firing
- worker/beat stop consuming tasks

Diagnosis:

1. Check service health:
   - `docker compose ps redis worker beat`
2. Inspect Redis memory and queue pressure:
   - `docker compose exec redis redis-cli INFO memory`
   - `docker compose exec redis redis-cli LLEN celery`
   - `docker compose exec redis redis-cli LLEN wb`
   - `docker compose exec redis redis-cli LLEN ozon`
3. Confirm the configured limits in `.env`:
   - `REDIS_URL`
   - container memory limits from `infra/docker/docker-compose.yml`
4. Inspect worker logs for broker disconnects or reconnect storms.

Recovery:

1. If Redis is unavailable, restart Redis first, then worker and beat:
   - `docker compose restart redis worker beat`
2. If memory is saturated, raise the Redis/container memory limit or free host memory before restarting.
3. Do not flush Redis unless you intentionally accept losing queued tasks.
4. After recovery, inspect missed ingestion windows and requeue them with bounded backfills.

Exit criteria:

- `/ready` no longer reports Redis failure
- queue lengths are draining
- worker and beat health endpoints recover

## ClickHouse storage pressure

Symptoms:

- `ClickHouseDiskPressure` alert is firing
- `/ready` returns `503` and backend logs `service=clickhouse`
- inserts or queries begin failing due to no free space

Diagnosis:

1. Check host and container disk usage:
   - `docker compose ps clickhouse`
   - `df -h`
2. Inspect ClickHouse disk stats:

```bash
docker compose exec clickhouse clickhouse-client -q "
SELECT
  name,
  path,
  formatReadableSize(free_space) AS free,
  formatReadableSize(total_space) AS total
FROM system.disks
ORDER BY name
"
```

3. Inspect the largest local tables:

```bash
docker compose exec clickhouse clickhouse-client -q "
SELECT
  database,
  table,
  formatReadableSize(sum(bytes_on_disk)) AS bytes_on_disk
FROM system.parts
WHERE active
GROUP BY database, table
ORDER BY sum(bytes_on_disk) DESC
LIMIT 20
"
```

Recovery:

1. Free host disk space if the Docker volume is constrained by the host.
2. Prune old raw data with the admin endpoint:
   - `curl -X POST http://localhost:18080/api/v1/admin/maintenance/prune-raw -H 'Content-Type: application/json' -H 'X-API-Key: <KEY>' -d '{"days":120}'`
3. If needed, temporarily stop noisy ingestion/backfills until disk pressure is reduced.
4. When storage is healthy again, re-run bounded backfills for any missed windows.

Exit criteria:

- `ClickHouseDiskPressure` alert clears
- ClickHouse inserts and reads succeed again
- free space returns above the alert threshold

## Upstream `429` / `5xx`

Symptoms:

- task failures spike for WB/Ozon ingestion jobs
- `MarketplaceTaskFailures` or `MarketplaceEmptyPayloadAnomaly` alert fires
- worker logs show `reason=server_error`, `reason=transport_error`, or upstream `429`

Diagnosis:

1. Inspect `sys_task_runs` and worker logs for the affected source/account.
2. Run `make check-tokens` to rule out expired or broken credentials.
3. Confirm whether the upstream incident is external before changing schedule/concurrency.
4. Check whether failures are limited to one dataset or all datasets for the same marketplace.

Recovery:

1. Leave retry behavior as-is; it already retries only `429`, `5xx`, and transport failures.
2. Do not increase concurrency during throttling incidents.
3. Once the upstream stabilizes, requeue the missed bounded window with:
   - `python3 scripts/backfill.py --marketplace wb --dataset sales --days 14 --api-key <KEY>`
   - `python3 scripts/backfill.py --marketplace ozon --dataset postings --days 14 --api-key <KEY>`
4. If marts lag behind after ingestion recovers, run the recent transform + marts rebuild actions.

Exit criteria:

- retries stop failing
- watermarks advance again
- backfilled period is visible in marts
