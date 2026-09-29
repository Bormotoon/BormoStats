# Observability

Prometheus scrape config lives in `infra/monitoring/prometheus/prometheus.yml`.
Prometheus alert rules live in `infra/monitoring/prometheus/alerts.yml`.
Rule test fixtures for `promtool` live in `infra/monitoring/prometheus/alerts.test.yml`.

Backend `/metrics` is served from memory: dependency gauges are refreshed by a
background thread every `METRICS_REFRESH_SECONDS` (30 s), so a scrape never waits on
ClickHouse or Redis. Set `METRICS_BEARER_TOKEN` and mount the same token for Prometheus
(`credentials_file` in `prometheus.yml`); the nginx proxy does not expose `/metrics`.

Health endpoints: `/health/live` (process up), `/health/ready` (ClickHouse + Redis,
cached for `READINESS_CACHE_SECONDS`), `/health/dependencies` (per-dependency status and
latency). `/health` and `/ready` remain as aliases.

Operational metrics exposed by backend `/metrics`:

- `service_readiness{service="redis|clickhouse"}`
- `redis_memory_used_bytes`
- `redis_memory_limit_bytes`
- `redis_memory_utilization_ratio`
- `clickhouse_disk_free_bytes{disk=...}`
- `clickhouse_disk_total_bytes{disk=...}`
- `clickhouse_disk_free_ratio{disk=...}`
- `backend_http_request_duration_seconds{method,route,status}`
- `backend_clickhouse_query_duration_seconds{operation}` / `backend_clickhouse_query_errors_total{operation}`

Worker metrics additionally include `marketplace_actions_total{source,status}`,
`webhook_deliveries_total{status}` and the data-quality gauges described in
[data_catalog.md](./data_catalog.md).

## Request correlation

Every response carries `X-Request-ID` (accepted from the client/proxy or generated).
The id is bound to all structured log lines of the request, stored in the audit log and
propagated as a Celery header, so worker log lines of tasks queued by that request carry
the same `request_id` (plus `task_id` / `task_name`).

Worker and beat metrics are exported separately:

- worker: `http://localhost:19101/metrics`
- beat: `http://localhost:19102/metrics`

Grafana dashboard JSONs:

- `dashboards/grafana/operational_overview.json`
- `dashboards/grafana/ingestion_freshness.json`

Configured alert rules:

- `MarketplaceTaskFailures`
- `MarketplaceWatermarkStale`
- `MarketplaceEmptyPayloadAnomaly`
- `RedisMemorySaturation`
- `RedisUnavailable`
- `ClickHouseUnavailable`
- `ClickHouseDiskPressure`
- `MartsStale`, `MartEmptyForYesterday`, `SchemaDrift`, `DataQualityChecksFailing`
- `TaskRetryStorm`, `ApiRateLimiting`, `BackendErrorRate`
- `WebhookDeadLetters`, `MarketplaceActionFailures`

Import the Grafana JSONs into a Prometheus datasource named `prometheus`
or update the datasource UID in the dashboard JSON before import.

Suggested rule test command:

```bash
promtool test rules infra/monitoring/prometheus/alerts.test.yml
```
