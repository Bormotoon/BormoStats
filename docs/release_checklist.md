# Release Checklist

## Pre-flight

1. Ensure the worktree is clean and every intended production change is committed.
2. Re-run the quality gates:
   - `make check` (ruff, ruff format, mypy strict, migration manifest, vulnerability waivers, pytest incl. Docker integration tests)
   - `make check-frontend` (`npm ci`, `npm audit --audit-level=high`, build) and `npm run test:e2e` in `frontend/`
   - `node --test "browser_extension/tests/*.test.mjs"`
3. If Prometheus rules changed: `promtool test rules infra/monitoring/prometheus/alerts.test.yml`.
4. Confirm CI is green, including the blocking `supply-chain-gate` job; no waiver in
   `security/vulnerability-waivers.yml` expires before the next release.
5. Update `CHANGELOG.md` (version, migrations, config changes, breaking changes).
6. Take a backup: `make backup`; for schema releases also run `make restore-check`.
7. Confirm `.env` (or secret files via `*_FILE`) contains production secrets and no placeholders.

## Deploy (rolling, zero downtime)

1. Build/pull the release images (pinned digests).
2. Apply migrations first: `make migrate` (the runner takes a lock; the previous release
   must tolerate the new schema — see [migration_policy.md](./migration_policy.md)).
3. Restart workers and beat (warm shutdown: running tasks finish within `stop_grace_period`,
   unfinished tasks are re-delivered thanks to `acks_late`).
4. Restart the backend (graceful shutdown drains in-flight requests; the proxy re-resolves
   the backend address automatically).
5. Watch healthchecks until backend, worker, beat and proxy are healthy.

## Post-deploy verification

1. `GET /health/live`, `GET /health/ready`, `GET /health/dependencies` (all `ok`).
2. Backend `/metrics` with the bearer token; worker/beat metrics on the ops network.
3. `/api/v1/admin/watermarks` and `/api/v1/admin/task-runs` with the platform key.
4. A user key can read `/api/v1/users/me` and `/api/v1/freshness`.
5. Grafana/Prometheus: task failures, stale watermarks/marts, Redis memory, ClickHouse disk,
   backend 5xx/429 rates, webhook dead letters, marketplace action failures.
6. Optional bounded smoke: recent transforms / marts rebuild via admin actions.

## Rollback triggers

- `/health/ready` stays unhealthy after warm-up
- worker or beat metrics stay unavailable
- task failures or marketplace action failures keep climbing
- ClickHouse or Redis cannot recover with the new release in place

## Rollback

1. Emergency stop for marketplace writes if relevant: `MARKETPLACE_ACTIONS_ENABLED=false`.
2. Redeploy the previous known-good images/commit (the previous release must run on the new
   schema; schema rollbacks are a last resort — `migrate-rollback` with `--allow-production`
   only after a backup).
3. Re-run readiness and metrics checks; requeue missed bounded ingestion windows.
4. Document the incident before the next deployment attempt.
