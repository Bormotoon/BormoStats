# Marketplace Analytics Audit Report

Date: March 7, 2026

## Current status

- Architecture remains aligned with the original plan: `backend`, `workers`, `collectors`, `warehouse`, `automation`, `infra`, and dashboards are present and wired together.
- The repository currently passes local quality gates:
  - `ruff check .`
  - `black --check .`
  - `mypy backend workers collectors automation warehouse scripts`
  - `pytest -q`
  - `pip-audit -r requirements.txt`
  - `docker compose --env-file .env -f infra/docker/docker-compose.yml config -q`
  - `./.venv/bin/python scripts/perf_smoke.py`

## Findings fixed during the latest audit

1. ClickHouse database name was not fully configurable.
   - Migration tracking and SQL migrations were hard-wired to `mp_analytics`, while runtime config exposed `CH_DB` as an operator setting.
   - Fixed by removing hard-coded `USE mp_analytics` from migrations, parameterizing migration bookkeeping by `CH_DB`, and removing the stale hard-coded database creation from initdb.

2. Integration and performance harnesses did not exercise non-default databases.
   - The Docker-backed test/perf environments always provisioned `mp_analytics`, so the configuration bug above could regress unnoticed.
   - Fixed by switching those harnesses to per-run custom database names and reusing the same client construction path as the backend.

3. Backend ClickHouse HTTP pool needed explicit sizing for concurrent API load.
   - Local performance smoke exposed connection-pool churn at `10` concurrent requests.
   - Fixed by adding `CH_POOL_MAXSIZE` (default `16`) and using an explicit ClickHouse HTTP pool manager in backend clients.

4. Audit documentation was stale.
   - The old report referenced already-fixed issues and obsolete test counts.
   - Fixed by rewriting this report and refreshing `docs/performance.md` with current measurements.

## Latest measured performance

- Ingestion smoke throughput: `6.22` raw rows/s
- API latency target: `p95 239.55 ms` at `10` concurrent requests / `50` total requests
- Transform backfill runtime: `0.229 s`
- Marts backfill runtime: `0.142 s`

## Residual operational note

- Full bootstrap still requires real secrets in `.env`. Placeholder values are intentionally rejected by startup/bootstrap validation, so "production ready" now depends on supplying valid WB/Ozon/admin credentials and strong ClickHouse passwords.
