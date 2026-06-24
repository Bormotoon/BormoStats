# Release Checklist

## Pre-flight

1. Ensure the worktree is clean and every intended production change is committed.
2. Re-run the full quality gate:
   - `ruff check .`
   - `black --check .`
   - `mypy backend workers collectors automation warehouse scripts`
   - `pytest -q`
3. If Prometheus rules changed, run:
   - `promtool test rules infra/monitoring/prometheus/alerts.test.yml`
4. If Dockerfiles or compose image digests changed, rebuild/pull the affected images before deploy.
5. Confirm `.env` contains the intended production secrets and no placeholders.

## Deploy

1. Pull/build the release artifacts.
2. Apply the stack with the pinned compose configuration.
3. Run bootstrap or migration smoke steps if the release contains schema/bootstrap changes.
4. Watch service startup until backend, worker, and beat healthchecks recover.

## Post-deploy verification

1. Verify:
   - `GET /health`
   - `GET /ready`
   - backend `/metrics`
   - worker `/metrics`
   - beat `/metrics`
2. Confirm `/api/v1/admin/watermarks` and `/api/v1/admin/task-runs` respond with a valid `X-API-Key`.
3. Check Grafana/Prometheus for:
   - task failures
   - stale watermarks
   - Redis memory saturation
   - ClickHouse disk pressure
4. Run one bounded admin action in a safe window if you need an end-to-end smoke test:
   - recent transforms
   - recent marts rebuild

## Rollback triggers

Rollback immediately if any of the following persists after the initial warm-up window:

- `/ready` stays unhealthy
- worker or beat metrics stay unavailable
- task failures continue climbing
- ClickHouse or Redis cannot recover with the new release in place

## Rollback

1. Redeploy the previous known-good pinned images/commit.
2. Re-run readiness and metrics checks.
3. Requeue any missed bounded ingestion windows.
4. Document the incident cause before the next deployment attempt.
