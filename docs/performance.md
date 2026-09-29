# Performance Validation

## Scope

This is a bounded performance smoke, not a full production soak test.
It exists to keep latency and task runtime regressions visible in CI/manual release checks.

Benchmark command:

```bash
./.venv/bin/python scripts/perf_smoke.py
```

Measured on March 7, 2026:

| Scenario | Target | Measured |
| --- | --- | --- |
| Ingestion smoke throughput | `>= 5` raw rows/s on the sample dataset | `6.22` raw rows/s |
| API latency (`/api/v1/sales/daily`) | `p95 <= 300 ms` at `10` concurrent requests / `50` total requests | `239.55 ms` |
| Transform backfill runtime | `<= 0.5 s` on the sample dataset | `0.229 s` |
| Marts backfill runtime | `<= 0.25 s` on the sample dataset | `0.142 s` |

## Safe concurrency limits

- worker concurrency: `4` on the default compose resource profile
- beat replicas: `1`
- transform rebuilds in parallel: `1`
- marts rebuilds in parallel: `1`

These limits reflect the current runtime and locking model:

- destructive rebuild pipelines are serialized by Redis locks
- beat is designed as a single scheduler instance
- backend ClickHouse clients must disable auto-generated sessions to avoid concurrent-session failures
- backend ClickHouse HTTP pool defaults to `CH_POOL_MAXSIZE=16` to sustain the benchmarked API concurrency without pool churn

## Notes

- The benchmark uses the same Docker-backed integration harness and sample marketplace payloads as the integration smoke tests.
- If the measured numbers regress beyond the targets above, treat the release as blocked until the regression is explained or the limits are updated deliberately.

## ClickHouse `FINAL` usage (audit 2026-09, §8.2)

- Hot analytics endpoints (`sales`, `stocks`, `funnel`, `ads`, `kpis`) read marts **without**
  `FINAL`: marts are rebuilt by delete-then-insert with `mutations_sync`, so no duplicate
  keys exist between rebuilds.
- `FINAL` remains on small dimension tables (`dim_*`, rules, subscriptions) where it is cheap
  and needed for last-write-wins semantics.
- Marts read with `FINAL` whose partition key is a function of a sorting-key column
  (`mrt_abc_xyz_analysis`, `mrt_breakeven_daily`, `mrt_pnl_monthly`) use
  `do_not_merge_across_partitions_select_final=1` (`PARTITION_LOCAL_FINAL`), so merging
  happens per partition in parallel. The setting is deliberately **not** global: tables
  such as `raw_competitor_products` are partitioned by a column outside the sorting key.
- Large rule/analysis listings are capped (`LIMIT 5000`), exports stream up to 1 M rows.
- If mart volumes grow further, prefer projections/materialized views for the dashboard
  aggregates over running `OPTIMIZE … FINAL`.

## Pagination

List endpoints fetch `limit + 1` rows to compute `has_more`/`next_offset` without a
`count()` over the mart; offsets are capped at 50 000. Clients that need everything should
use `POST /api/v1/exports` instead of deep offsets.

## Query budget

The API client sends `max_execution_time = CH_QUERY_TIMEOUT_SECONDS` (default 30 s) with every
query and uses a slightly longer HTTP read timeout; slow queries fail fast with 5xx instead of
tying up workers. Latency and errors are exported as
`backend_clickhouse_query_duration_seconds` / `backend_clickhouse_query_errors_total`.
