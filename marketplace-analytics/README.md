# Marketplace Analytics (WB + Ozon)

Self-hosted analytics stack for Wildberries and Ozon seller accounts.

## What is included

- `workers` collect data from WB/Ozon APIs into ClickHouse raw tables
- SQL transforms build `stg_*` and `mrt_*` analytics layers
- `backend` provides read-only metrics API and admin endpoints
- `automation` executes YAML rules and sends Telegram alerts
- `metabase` is available in docker-compose for dashboards

## Quick start

1. Create env file:

```bash
cp .env.example .env
```

2. Fill API tokens and admin key in `.env`.
   Optional: set `WB_TOKEN_CREATED_AT` to get expiry warning (WB tokens are valid for 180 days).

3. Run bootstrap (start services + migrations + smoke checks):

```bash
make bootstrap
```

4. Check health:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

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

## Data model

- Raw ingestion tables: `raw_*`
- Staging canonical layer: `stg_*`
- BI marts: `mrt_*`

See `docs/architecture.md` and `docs/metabase.md` for details.
