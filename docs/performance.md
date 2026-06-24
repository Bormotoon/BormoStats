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
