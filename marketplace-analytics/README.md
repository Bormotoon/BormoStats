# Marketplace Analytics (WB + Ozon)

Self-hosted analytics stack for Wildberries and Ozon seller accounts.

## Scope

This project is designed for data from your own seller accounts only.
It does not collect competitor/category intelligence and does not scrape marketplace storefronts.

## What is included

- `workers` collect data from WB/Ozon APIs into ClickHouse raw tables
- SQL transforms build `stg_*` and `mrt_*` analytics layers
- `backend` provides read-only metrics API and admin endpoints
- `backend /ui` provides a full Material 3 style web interface (dashboard + domain pages)
- `automation` executes YAML rules and sends Telegram alerts
- `metabase` is available in docker-compose for dashboards

## Required credentials

- WB:
  - `WB_TOKEN_STATISTICS` (statistics endpoints)
  - `WB_TOKEN_ANALYTICS` (analytics endpoints)
  - optional `WB_TOKEN_CREATED_AT` for expiry reminder (WB tokens are valid for 180 days)
- Ozon:
  - `OZON_CLIENT_ID`
  - `OZON_API_KEY`
  - optional `OZON_PERF_API_KEY` for ads/performance endpoints
- Admin API:
  - `ADMIN_API_KEY`
- Telegram alerts:
  - `TG_BOT_TOKEN`, `TG_CHAT_ID`

## Quick start

1. Create env file:

```bash
cp .env.example .env
```

2. Fill API tokens and admin key in `.env`.
If ports conflict with other containers (`pykumir` or anything else), change:
`CH_HTTP_HOST_PORT`, `BACKEND_HOST_PORT`, `METABASE_HOST_PORT`, `STACK_NAME`.

3. Run bootstrap (start services + migrations + smoke checks):

```bash
make bootstrap
```

4. Check health:

```bash
curl http://localhost:18080/health
curl http://localhost:18080/ready
curl http://localhost:18080/metrics
```

Open GUI:

```bash
xdg-open http://localhost:18080/ui/
```

Default ports from `.env.example`:
- backend: `http://localhost:18080`
- metabase: `http://localhost:13000`
- clickhouse http: `http://localhost:18123`

5. Open Metabase at `http://localhost:13000` (or your `METABASE_HOST_PORT`) and connect to ClickHouse using values from `.env`.

## Main API endpoints

- `GET /api/v1/sales/daily`
- `GET /api/v1/stocks/current`
- `GET /api/v1/funnel/daily`
- `GET /api/v1/ads/daily`
- `GET /api/v1/kpis`

Admin (`X-API-Key` required):

- `GET /api/v1/admin/watermarks`
- `POST /api/v1/admin/run-task`
- `POST /api/v1/admin/backfill`
- `GET /api/v1/admin/task-runs`

## Useful commands

- `make logs` — follow container logs
- `make check-tokens` — validate env values + API credentials
- `python3 scripts/backfill.py --marketplace wb --dataset sales --days 14 --api-key <KEY>`
- `python3 scripts/backfill.py --marketplace ozon --dataset finance --days 30 --api-key <KEY>`

## Telegram alerts

1. Set `TG_BOT_TOKEN` and `TG_CHAT_ID` in `.env`.
2. Ensure `tasks.maintenance.run_automation_rules` runs (beat schedule).
3. Keep rules in `automation/rules/*.yml` aligned with your thresholds.

## Troubleshooting quick links

- API rate limits / upstream errors: see `docs/troubleshooting.md` (`429/5xx` section)
- No new data: check watermarks and manual backfill instructions
- Capability/premium issues on Ozon methods: check `sys_task_runs.meta_json`

## Data model

- Raw ingestion tables: `raw_*`
- Staging canonical layer: `stg_*`
- BI marts: `mrt_*`

See `docs/architecture.md` and `docs/metabase.md` for details.
