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

- `hist_*`: append-only, git-like history of every product card state and every ingested version
  of each `raw_*` row; never pruned (see [history.md](./history.md))

## Scheduling baseline

`tasks.reports.collect_daily` starts once a day at 06:00 (`TZ=Europe/Moscow`).
It runs catalogue and marketplace collection, then staging transforms, marts,
data quality checks and recommendations in dependency order. Successful steps
are checkpointed in Redis, so retries resume without collecting completed sources
again. Independent collector, backfill and rebuild timers are disabled.

WB sales/orders use last-change watermarks; its funnel refreshes 14 days.
Ozon postings refresh 90 days of statuses; finance and advertising refresh recent
corrections. SKU ad reports use stable daily periods and a Moscow-day cache.
Staging and marts rebuild 90 days; monthly P&L rebuilds touched calendar months.

Raw history import/pruning, exports cleanup, reviews, competitor monitoring,
marketplace rules, automation rules and the existing digest keep their own schedules.
See [customization review](customization-review.md) for source dependencies,
verification requirements and operational limitations.

## Reliability

- Watermarks (`sys_watermarks`) for incremental collectors
- Redis locks (`lock:{source}:{account_id}`) to prevent parallel same-source runs
- Task run audit (`sys_task_runs`) with status and message
- Prometheus metrics endpoint: `/metrics`
- Worker counters/gauges/histograms for rows, durations, watermark lag and empty payloads

## Project boundaries

System works only with seller's own account data (WB/Ozon APIs).
No competitor/category intelligence is collected.
