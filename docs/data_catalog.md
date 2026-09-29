# Data catalog

All analytics tables are keyed by `(marketplace, account_id)`; an account belongs to one
organization through `dim_account.organization_id`, which is how every API query is
tenant-scoped. Money is in RUB, days are `Date` in the warehouse timezone, timestamps
are stored as UTC `DateTime`.

## Marts

| Table | Grain | Source | Rebuilt | Acceptable delay |
|---|---|---|---|---|
| `mrt_sales_daily` | day × account × product | `stg_sales` (WB sales, Ozon postings) | every 30 min (`build_marts_recent`), 14-day backfill nightly | ≤ 2 h (`MartsStale`) |
| `mrt_stock_daily` | day × account × product × warehouse | `stg_stocks` snapshots | every 30 min | ≤ 2 h |
| `mrt_funnel_daily` | day × account × product | WB funnel report | every 30 min | ≤ 2 h (report itself lags ~1 day) |
| `mrt_ads_daily` | day × account × campaign | Ozon ads statistics | every 30 min, 60-day window | ≤ 6 h |
| `mrt_profit_daily` | day × account × product | sales + `dim_product_cost` + finance ops | every 30 min | ≤ 2 h |
| `mrt_abc_xyz_analysis` | day × account × product | 60-day sales | daily | ≤ 1 day |
| `mrt_breakeven_daily` | day × account × product | costs, commissions, logistics | daily | ≤ 1 day |
| `mrt_pnl_monthly` | month × organization × account | profit + ads + `dim_additional_expense` | daily | ≤ 1 day |

## Metrics

| Metric | Formula | Table |
|---|---|---|
| Revenue | `sum(revenue)` — seller price × quantity for completed sales | `mrt_sales_daily` |
| Payout | `sum(payout)` — amount paid out by the marketplace (nullable when unknown) | `mrt_sales_daily` |
| Returns | `sum(returns_qty)` | `mrt_sales_daily` |
| Stock | `sum(stock_end)` at the latest snapshot day | `mrt_stock_daily` |
| CR to cart / order | `adds_to_cart / views`, `orders / views` (0 when no views) | `mrt_funnel_daily` |
| ACOS | `cost / revenue` (0 when no revenue) | `mrt_ads_daily` |
| ROMI | `(revenue − cost) / cost` (0 when no cost) | `mrt_ads_daily` |
| Turnover days | `stock_end / avg_daily_sales` over 14 days | insights trigger |
| ABC class | cumulative revenue share: A ≤ 80 %, B ≤ 95 %, C rest | `mrt_abc_xyz_analysis` |
| XYZ class | coefficient of variation of daily quantity: X ≤ 10 %, Y ≤ 25 %, Z rest | `mrt_abc_xyz_analysis` |
| Break-even price | cost + logistics + commission share | `mrt_breakeven_daily` |

## Quality signals

The hourly `run_data_quality_checks` task exports:

| Prometheus metric | Meaning | Alert |
|---|---|---|
| `mart_freshness_seconds{table}` | time since the mart was rebuilt | `MartsStale` (> 2 h) |
| `mart_rows_yesterday{table}` | rows for yesterday (row-count drift / empty loads) | `MartEmptyForYesterday` |
| `data_null_rate{table,column}` | share of NULL/empty key values over 7 days | dashboard |
| `schema_drift_missing_columns{table}` | expected columns missing | `SchemaDrift` |
| `data_quality_failures{check}` | stale marts, duplicate grains, impossible timestamps, invalid values, watermark regressions | `DataQualityChecksFailing` |
| `watermark_lag_seconds{source,account_id}` | marketplace API lag per collector | `MarketplaceWatermarkStale` |
