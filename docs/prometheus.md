# Prometheus scrape config

Worker and beat metrics use separate in-process HTTP endpoints.
The worker endpoint runs with `prometheus_client` multiprocess mode so prefork Celery child processes contribute to the same scrape payload.

Default local targets from `.env.example`:

- worker: `localhost:19101`
- beat: `localhost:19102`

Example scrape config:

```yaml
scrape_configs:
  - job_name: marketplace-worker
    static_configs:
      - targets:
          - localhost:19101

  - job_name: marketplace-beat
    static_configs:
      - targets:
          - localhost:19102
```

Expected worker metrics include:

- `task_duration_seconds`
- `task_runs_total`
- `watermark_lag_seconds`
- `empty_payload_total`
