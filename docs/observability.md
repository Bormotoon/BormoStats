# Observability

Prometheus scrape config lives in `infra/monitoring/prometheus/prometheus.yml`.
Prometheus alert rules live in `infra/monitoring/prometheus/alerts.yml`.
Rule test fixtures for `promtool` live in `infra/monitoring/prometheus/alerts.test.yml`.

Operational metrics exposed by backend `/metrics`:

- `service_readiness{service="redis|clickhouse"}`
- `redis_memory_used_bytes`
- `redis_memory_limit_bytes`
- `redis_memory_utilization_ratio`
- `clickhouse_disk_free_bytes{disk=...}`
- `clickhouse_disk_total_bytes{disk=...}`
- `clickhouse_disk_free_ratio{disk=...}`

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

Import the Grafana JSONs into a Prometheus datasource named `prometheus`
or update the datasource UID in the dashboard JSON before import.

Suggested rule test command:

```bash
promtool test rules infra/monitoring/prometheus/alerts.test.yml
```
