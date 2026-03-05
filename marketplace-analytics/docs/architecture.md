# Architecture

## Pipeline

1. Celery beat triggers collectors (`wb_collect`, `ozon_collect`)
2. Collectors write JSON payload + normalized fields into `raw_*`
3. Transform task writes canonical records into `stg_*`
4. Mart task aggregates into `mrt_*`
5. FastAPI reads marts and serves API
6. Automation engine runs SQL rules and executes actions (Telegram)

## Components

- ClickHouse: analytical warehouse (`mp_analytics`)
- Redis: Celery broker and distributed locks
- Worker: ingestion/transforms/marts/maintenance
- Backend: read/admin API
- Metabase: BI dashboards

## Data layers

- `raw_*`: source payload + key fields for idempotent ingestion
  - WB: `raw_wb_sales`, `raw_wb_orders`, `raw_wb_stocks`, `raw_wb_funnel_daily`
  - Ozon: `raw_ozon_postings`, `raw_ozon_posting_items`, `raw_ozon_stocks`, `raw_ozon_ads_daily`, `raw_ozon_finance_ops`
- `stg_*`: canonical normalized layer
  - `stg_sales`, `stg_orders`, `stg_stocks`, `stg_funnel_daily`, `stg_ads_daily`, `stg_finance_ops`
- `mrt_*`: BI marts
  - `mrt_sales_daily`, `mrt_stock_daily`, `mrt_funnel_daily`, `mrt_ads_daily`

## Scheduling baseline

- WB:
  - `wb_sales_incremental`: every 15 min
  - `wb_orders_incremental`: every 15 min
  - `wb_stocks_snapshot`: every 30 min
  - `wb_funnel_roll`: hourly (7-day rolling window)
  - backfills: daily window tasks
- Ozon:
  - `ozon_postings_incremental`: every 20 min
  - `ozon_stocks_snapshot`: every 30 min
  - `ozon_finance_incremental`: every 6 hours
  - `ozon_ads_daily`: every 6 hours (requires `OZON_PERF_API_KEY`)
- ELT and marts:
  - `transform_all_recent`: every 30 min
  - `build_marts_recent`: hourly
  - `build_marts_backfill_14d`: daily
- Automation and maintenance:
  - `run_automation_rules`: 3 times per day
  - `prune_old_raw`: daily

## Reliability

- Watermarks (`sys_watermarks`) for incremental collectors
- Redis locks (`lock:{source}:{account_id}`) to prevent parallel same-source runs
- Task run audit (`sys_task_runs`) with status and message
- Prometheus metrics endpoint: `/metrics`
- Worker counters/gauges/histograms for rows, durations, watermark lag and empty payloads

## Project boundaries

System works only with seller's own account data (WB/Ozon APIs).
No competitor/category intelligence is collected.
