# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/); database migrations are listed per release.

## [1.1.0] — 2026-09-29

Remediation of the September 2026 audit (`AUDIT_REPORT.md`); details per finding in
[docs/audit_remediation.md](docs/audit_remediation.md).

### Breaking changes

- **Every `/api/v1/*` endpoint requires `X-API-Key`.** Analytics reads were anonymous before;
  `PUBLIC_READ_API=true` restores that for local development only (rejected in stage/prod).
- **User API keys are hashed.** Existing plaintext keys keep working (migration `0021` converts
  them, they are upgraded to scrypt on first use), but keys are no longer returned by
  `GET /users`; new keys are shown once on create/rotate. New format: `bsk_<id>_<secret>`.
- **Tenancy comes from the key.** `organization_id` in request bodies (users, expenses) is ignored/removed;
  the platform key selects an organization with `X-Organization-Id`.
- A user without a membership row in its organization now gets 403 (was treated as viewer).
- Webhook secrets are server-generated, encrypted at rest and returned once; migration `0024`
  clears previously stored plaintext secrets — rotate existing subscriptions.
- Bidder/repricer rules default to **dry-run**; live changes need `execute:marketplace` and
  `MARKETPLACE_ACTIONS_ENABLED=true`.
- Compose requires `REDIS_PASSWORD` and `BOOTSTRAP_CH_ADMIN_PASSWORD`; Redis uses an ACL user
  (`REDIS_USERNAME`, default `bormostats`).
- `apply_migrations.py --rollback` was replaced by `apply_migrations.py rollback --target V`.
- WB stock push now uses the Marketplace API and `WB_TOKEN_MARKETPLACE`; `sku` must be the
  numeric size id (`chrtId`).

### Added

- `AuthContext` with an explicit role matrix and scopes; `/users/me` principal info; key expiry,
  revocation and org-wide revoke; admin network allowlist; audit log of all mutating requests.
- Webhook delivery engine: HMAC-SHA256 signatures with timestamp, idempotency key, retries with
  backoff, dead letters, SSRF protection with IP pinning, test delivery and secret rotation.
- Real marketplace clients for WB bids/prices/stocks and Ozon prices/stocks with dry-run,
  idempotency, per-run budget, kill switch and `sys_marketplace_actions` audit trail.
- Insights: per-organization triggers, dedupe keys, full UUIDs, `insight.created` events.
- Async CSV exports (`/api/v1/exports`), data freshness endpoint and UI banner.
- `/health/live`, `/health/ready` (cached), `/health/dependencies`; protected `/metrics`
  (bearer token, background refresh); authenticated `/api/v1/openapi.json`.
- Request correlation (`X-Request-ID`) across proxy → API → Celery; HTTP and ClickHouse metrics.
- Data-quality metrics (freshness, row counts, null rates, schema drift) and new alerts
  (stale marts, schema drift, retry storms, 429/5xx rates, webhook dead letters, action failures).
- Migration runner: lock, journal, checksums, postconditions, manifest, `status`/`verify`/`rollback`.
- `make init ENV=…`, `make backup`, `make restore-check`, `make lock`, `make check-frontend`.
- `*_FILE` secret loading (Docker/Kubernetes secrets).
- Tests: auth matrix over every route, tenant isolation on real ClickHouse, SQL contracts for
  rules/triggers/exports, worker suite, Playwright E2E smoke, browser-extension tests.

### Fixed

- `str.format` over SQL with ClickHouse binds crashed bidder campaign sync, insights task
  updates and all organization/member/shop-account writes.
- Celery workers only consumed the `etl` queue: WB/Ozon/competitor/automation tasks never ran.
- Bidder/repricer/insights tasks could not be imported and were never registered.
- Enum roles returned by ClickHouse by name broke user authentication.
- Insights turnover trigger and `turnover_alert` rule queried a non-existent column;
  `now() - 14` subtracted seconds instead of days.
- Naive UTC datetimes were shifted by the process timezone when bound to ClickHouse.
- `make up` passed a wrong `.env` path; the HTTP→HTTPS redirect used the container port;
  the proxy kept a stale backend IP after a backend restart.
- ClickHouse readiness gauge was always 0 (missing `system.disks` grant).
- WB stock updates were posted to the read-only Statistics API; product-cost upsert crashed;
  PIM product search referenced an unknown alias.
- Frontend: key entered in settings was ignored until reload; bid sliders fired a request per
  pixel; `make frontend` removed a directory outside the repository.
- Browser extension: DOM-injection of scraped data, API key in synced storage, content script
  calling the API directly, competitor-price payload rejected by the API.
- Rate limiter returned 500 instead of 429 and shared one bucket between all clients.

### Security

- npm advisories fixed (react-router 7.18.4, postcss 8.5.28, nanoid 3.3.19).
- Python dependencies split into `requirements.in` + hash-locked `requirements.txt`.
- CI: actions pinned to commit SHAs, blocking `pip-audit`/Grype gate with expiring waivers,
  SARIF upload, SBOM retention, `npm audit`.

### Migrations

`0021_api_key_hashing`, `0022_marketplace_actions`, `0023_insights_dedupe`,
`0024_webhook_delivery`, `0025_audit_actor`, `0026_export_jobs` (all with rollback scripts).

## [1.0.0] — 2026-06-25

Initial public release.
