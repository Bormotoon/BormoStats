# Architecture

## Pipeline

1. Celery beat triggers collectors (`wb_collect`, `ozon_collect`, `ym_collect`)
2. Collectors write JSON payload + normalized fields into `raw_*` (and archive versions in `hist_*`)
3. Transform task writes canonical cross-marketplace records into `stg_*` and syncs `dim_product`
4. Mart task aggregates into `mrt_*`
5. FastAPI reads marts (and computes streaming $O(N + S)$ SKU unit economics) and serves the REST API + React SPA
6. Automation engine runs YAML/SQL rules, generates actionable tasks, and executes marketplace actions (two-phase commit with read-after-write reconciliation) and Telegram alerts

## Components

- ClickHouse 26.3 LTS: analytical warehouse (`mp_analytics`) + append-only history store (`hist_*`)
- Redis 8: Celery broker, query cache, and distributed locks
- Worker: ingestion, transforms, marts, repricer, bidder, review replies, webhooks, maintenance
- Backend: FastAPI REST/admin API and React 19 web UI
- Metabase: BI dashboards

## Data layers

- `raw_*`: source payload + key fields for idempotent ingestion
  - WB: `raw_wb_sales`, `raw_wb_orders`, `raw_wb_stocks`, `raw_wb_funnel_daily`, `raw_wb_sales_report`
  - Ozon: `raw_ozon_postings`, `raw_ozon_posting_items`, `raw_ozon_stocks`, `raw_ozon_ads_daily`, `raw_ozon_finance_ops`, `raw_ozon_finance_balance`, `raw_ozon_realization_reports`, `raw_ozon_sku_ad_reports`, `raw_ozon_cis_buyouts`, `raw_ozon_campaigns`, `raw_ozon_funnel_import`
  - Yandex Market: `raw_ym_orders`, `raw_ym_order_stats`, `raw_ym_delivered_snapshots`, `raw_ym_stocks`, `raw_ym_prices`, `raw_ym_tariff_quotes`, `raw_ym_offer_mappings`, `raw_ym_funnel`, `raw_ym_ads`, `raw_ym_finance`, `raw_ym_campaigns`
- `stg_*`: canonical normalized layer
  - `stg_sales`, `stg_orders`, `stg_stocks`, `stg_funnel_daily`, `stg_ads_daily`, `stg_finance_ops`
- `mrt_*`: BI marts
  - `mrt_sales_daily`, `mrt_stock_daily`, `mrt_funnel_daily`, `mrt_ads_daily`, `mrt_profit_daily`, `mrt_supply_planning_daily`, `mrt_abc_xyz_analysis`, `mrt_finance_daily`, `mrt_price_current`, `mrt_pnl_monthly`

- `hist_*`: append-only, git-like history of every product card state and every ingested version
  of each `raw_*` row; never pruned (see [history.md](./history.md))

## Scheduling baseline

- WB:
  - `wb_sales_incremental`: every 15 min
  - `wb_orders_incremental`: every 15 min
  - `wb_stocks_snapshot`: every 30 min
  - `wb_funnel_roll`: hourly (7-day rolling window)
  - `wb_finance_incremental` & `wb_balance_snapshot`: hourly
  - backfills: daily window tasks
- Ozon:
  - `ozon_postings_incremental`: every 20 min
  - `ozon_stocks_snapshot`: every 30 min
  - `ozon_finance_incremental`: every 6 hours (`/v1/finance/accrual/by-day`, one request chain per Moscow day, last 3 days re-read)
  - `ozon_ads_daily` & `ozon_sku_ad_reports`: every 6 hours (Performance API, requires `OZON_PERF_CLIENT_ID` / `OZON_PERF_CLIENT_SECRET`)
  - `ozon_realization_reports`, `ozon_cis_buyouts`, `ozon_campaigns`: scheduled & backfill tasks
- Yandex Market (`ym` queue):
  - `ym_orders_incremental`, `ym_stocks_snapshot`, `ym_funnel_roll`, `ym_ads_daily`, `ym_finance_incremental`, `ym_prices_snapshot`, `ym_tariffs_snapshot`: scheduled incremental and snapshot tasks
- ELT and marts:
  - `transform_all_recent`: every 30 min
  - `build_marts_recent`: every 30 min / hourly
  - `build_marts_backfill_14d`: daily
- History (`tasks.history.*`):
  - `wb_catalog_snapshot`, `ozon_catalog_snapshot`, `ym_catalog_snapshot`: hourly (product cards, prices, attributes)
  - `backfill_raw_archive`: daily, one-off import per raw table; `prune_old_raw` waits for it
- Automation and maintenance:
  - `sync_reviews`: every 15 min
  - `reconcile_applied_actions`: periodic read-after-write verification of pending/applied marketplace actions
  - `run_automation_rules`: 3 times per day
  - `prune_old_raw`: daily

## Reliability

- Watermarks (`sys_watermarks`) for incremental collectors
- Redis locks (`lock:{source}:{account_id}`) to prevent parallel same-source runs
- Task run audit (`sys_task_runs`) with status and message
- Two-phase marketplace action ledger (`sys_marketplace_actions`: `pending` → `applied`/`failed` → `confirmed`)
- Prometheus metrics endpoint: `/metrics`
- Worker counters/gauges/histograms for rows, durations, watermark lag and empty payloads

## Project boundaries

System works with seller's own account data across Wildberries, Ozon, and Yandex Market official APIs (plus optional opt-in SKU/keyword tracking via the client-side browser extension).
No marketplace-wide catalog scraping or market-share intelligence is collected.
