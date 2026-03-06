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
- ClickHouse bootstrap admin:
  - `BOOTSTRAP_CH_ADMIN_USER`
  - `BOOTSTRAP_CH_ADMIN_PASSWORD`
- Telegram alerts:
  - `TG_BOT_TOKEN`, `TG_CHAT_ID`

## Quick start

1. Create env file:

```bash
cp .env.example .env
```

Alternative environment-specific starting points:

- `cp .env.dev.example .env`
- `cp .env.stage.example .env`
- `cp .env.prod.example .env`

2. Fill required secrets in `.env` before running anything:
   - set a dedicated bootstrap ClickHouse admin in `BOOTSTRAP_CH_ADMIN_USER` / `BOOTSTRAP_CH_ADMIN_PASSWORD`
   - set a dedicated ClickHouse app password in `CH_PASSWORD`
   - generate a random `ADMIN_API_KEY` (for example `openssl rand -hex 32`)
   - set all required WB/Ozon credentials
   - optionally set `CH_RO_USER` + `CH_RO_PASSWORD` for a dedicated Metabase read-only user

Bootstrap now fails fast if `.env` still contains placeholders or blank required credentials.
If ports conflict with other containers (`pykumir` or anything else), change:
`CH_HTTP_HOST_PORT`, `BACKEND_HOST_PORT`, `BACKEND_TLS_HOST_PORT`, `METABASE_HOST_PORT`, `STACK_NAME`.

3. Run bootstrap (start services + migrations + smoke checks):

```bash
make bootstrap
```

4. Check health:

```bash
curl http://localhost:18080/health
curl -k https://localhost:18443/ready
curl -k https://localhost:18443/metrics
```

Open GUI:

```bash
xdg-open https://localhost:18443/ui/
```

The web UI keeps `ADMIN_API_KEY` only in memory for the current tab.
Reloading the page or opening a new tab requires entering the key again.
The backend, worker and beat containers run as an unprivileged user with a read-only root
filesystem and a writable `tmpfs` mounted at `/tmp`.
The public entrypoint is the nginx reverse proxy; backend is not published directly on a host port.

Default ports from `.env.example`:
- backend http proxy: `http://localhost:18080`
- backend https proxy: `https://localhost:18443`
- metabase (loopback only): `http://localhost:13000`
- clickhouse http (loopback only): `http://localhost:18123`
- worker metrics (loopback only): `http://localhost:19101/metrics`
- beat metrics (loopback only): `http://localhost:19102/metrics`

5. Open Metabase at `http://localhost:13000` (or your `METABASE_HOST_PORT`) and connect to ClickHouse using your configured app credentials or the optional `CH_RO_USER` / `CH_RO_PASSWORD`.

## Main API endpoints

- `GET /api/v1/sales/daily`
- `GET /api/v1/stocks/current`
- `GET /api/v1/funnel/daily`
- `GET /api/v1/ads/daily`
- `GET /api/v1/kpis`

Public analytics endpoints validate `marketplace` (`wb|ozon`), constrain `account_id` format,
enforce pagination via `limit` + `offset`, and cap heavy date-range queries at 92 days.
Error responses use a shared envelope: `{"detail":"...","error":{"code":"...","message":"..."}}`.

Admin (`X-API-Key` required):

- `GET /api/v1/admin/watermarks`
- `POST /api/v1/admin/backfill`
- `POST /api/v1/admin/transforms/recent`
- `POST /api/v1/admin/transforms/backfill`
- `POST /api/v1/admin/marts/recent`
- `POST /api/v1/admin/marts/backfill`
- `POST /api/v1/admin/maintenance/run-automation`
- `POST /api/v1/admin/maintenance/prune-raw`
- `GET /api/v1/admin/task-runs`

## Useful commands

- `make logs` — follow container logs
- `make check-tokens` — validate env values + API credentials
- `python3 scripts/backfill.py --marketplace wb --dataset sales --days 14 --api-key <KEY>`
- `python3 scripts/backfill.py --marketplace ozon --dataset finance --days 30 --api-key <KEY>`

## Dependency policy

- `requirements.txt` and `requirements-dev.txt` are fully pinned snapshots of tested environments.
- Update Python pins only from a clean virtualenv and rerun `ruff check .`, `black --check .`, `mypy backend workers collectors automation warehouse scripts`, and `pytest -q`.
- Dockerfiles and `infra/docker/docker-compose.yml` pin images by digest. When refreshing them, pull the candidate image first, update the digest, then rerun bootstrap and migration smoke checks before merging.
- CI also runs `pip-audit`, container image vulnerability scans, and SBOM generation; see `docs/supply_chain_security.md`.

## Runtime guardrails

- `backend`, `worker` and `beat` run as non-root user `app` (uid/gid `10001`).
- These application containers use `read_only: true`, `no-new-privileges`, and `tmpfs` for `/tmp`.
- Healthchecks probe backend `/ready` and worker/beat `/metrics`.
- CPU and memory limits are configurable through the `*_MEMORY_LIMIT`, `*_MEMORY_RESERVATION` and `*_CPU_LIMIT` variables in `.env`.
- `tasks.maintenance.run_data_quality_checks` runs hourly and logs structured failures into `sys_task_runs.meta_json`.

## Telegram alerts

1. Set `TG_BOT_TOKEN` and `TG_CHAT_ID` in `.env`.
2. Ensure `tasks.maintenance.run_automation_rules` runs (beat schedule).
3. Keep rules in `automation/rules/*.yml` aligned with your thresholds.

## Redis retention

Celery uses Redis as a broker only.
Task results are not persisted in Redis; operational history is tracked in `sys_task_runs`
and exposed via `GET /api/v1/admin/task-runs`.

## Troubleshooting quick links

- API rate limits / upstream errors: see `docs/troubleshooting.md` (`429/5xx` section)
- No new data: check watermarks and manual backfill instructions
- Capability/premium issues on Ozon methods: check `sys_task_runs.meta_json`

## Operations docs

- `docs/environments.md` for `dev/stage/prod` env model and promotion flow
- `docs/credential_rotation.md` for secret rotation and least-privilege review
- `docs/disaster_recovery.md` for backups, restore flow, and RPO/RTO
- `docs/migration_policy.md` for forward-only migration discipline and dry-run review
- `docs/performance.md` for load targets, measured perf smoke results, and safe concurrency limits
- `docs/release_management.md` and `docs/release_notes_template.md` for versioning, rollout, and rollback discipline
- `docs/troubleshooting.md` for fast incident lookup
- `docs/runbooks.md` for step-by-step recovery procedures
- `docs/release_checklist.md` for deployment and rollback checks

## Data model

- Raw ingestion tables: `raw_*`
- Staging canonical layer: `stg_*`
- BI marts: `mrt_*`

See `docs/architecture.md` and `docs/metabase.md` for details.
Prometheus scrape examples for worker and beat are in `docs/prometheus.md`.
Alert rules and operational dashboards are documented in `docs/observability.md`.
