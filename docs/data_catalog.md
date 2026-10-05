# Data catalog

All analytics tables are keyed by `(marketplace, account_id)`; an account belongs to one
organization through `dim_account.organization_id`, which is how every API query is
tenant-scoped. Money is in RUB. A day is a **Moscow day**, as in the marketplaces' own
reports; see [Time](#time) for how timestamps are stored.

## Marts

| Table | Grain | Source | Rebuilt | Acceptable delay |
|---|---|---|---|---|
| `mrt_sales_daily` | day × account × product | `stg_sales`: WB sales report (`S…` sales, `R…` returns), Ozon realization accruals | every 30 min (`build_marts_recent`), 14-day backfill nightly | ≤ 2 h (`MartsStale`) |
| `mrt_stock_daily` | day × account × product × warehouse | `stg_stocks` snapshots | every 30 min | ≤ 2 h |
| `mrt_funnel_daily` | day × account × product | WB funnel report | every 30 min | ≤ 2 h (report itself lags ~1 day) |
| `mrt_ads_daily` | day × account × campaign | Ozon ads statistics | every 30 min, 60-day window | ≤ 6 h |
| `mrt_profit_daily` | day × account × product | `stg_sales` + `dim_product_cost` | every 30 min | ≤ 2 h |
| `mrt_supply_planning_daily` | account × product (today) | `stg_sales` + latest `stg_stocks` snapshot | every 30 min | ≤ 2 h |
| `mrt_abc_xyz_analysis` | day × account × product | `mrt_sales_daily`; one snapshot per day, the API shows the latest | every 30 min (today's snapshot) | ≤ 2 h |
| `mrt_finance_daily` | day × account | Ozon `/v1/finance/balance` per day; WB realization report lines (`/api/finance/v1/sales-reports/detailed`, daily reports) + balance widget snapshots | every 30 min; collectors hourly | Ozon ≤ 1 h; WB report of a day arrives the next day |
| `mrt_breakeven_daily` | day × account × product | costs, commissions, logistics | **not built yet** (no task writes it) | — |
| `mrt_pnl_monthly` | month × organization × account | `mrt_finance_daily` + cost of goods + Ozon ads; `dim_additional_expense` as rows with an empty marketplace | every 30 min (months the window touches) | ≤ 2 h |

### Product dictionary

`dim_product` (account × product × WB size) names the products the marts and the API
(`title` in `/sales/daily`, `/stocks/current`; `product_name` in profit and supply planning)
refer to. Three syncs feed it on every transform, the last one winning on the same key:
products seen in WB sales, products seen in Ozon postings (title only), and the catalogue
from the history store — every card, sold or not, with title, brand and category (WB:
`subjectName`; Ozon cards carry only `type_id`, so their category stays empty). The
`product_id` is the id the marts use: WB `nmID`, Ozon **SKU** (`ozon_product_id` keeps the
product id). The catalogue needs `HISTORY_ENABLED` and, for WB, `WB_TOKEN_CONTENT`.
The catalogue also sets `image_url`, a thumbnail of the card's first photo (WB `c246x328`,
Ozon `primary_image`); `/sales/daily` returns it with the seller's article (`offer_id`).

## Metrics

| Metric | Formula | Table |
|---|---|---|
| Sales (qty) | units bought out on the day, returns excluded | `mrt_sales_daily.qty` |
| Revenue | `sum(revenue)` — sales at the seller's price after the seller's discount (WB `priceWithDisc`, Ozon `seller_price`), returns excluded | `mrt_sales_daily` |
| Payout | `sum(payout)` — amount due for the goods before logistics and storage (WB `forPay`, Ozon `sale_amount + commission`), net of returns | `mrt_sales_daily` |
| Returns | `sum(returns_qty)` — units returned, positive | `mrt_sales_daily` |
| Profit | payout − cost price × units kept by buyers; margin = profit / (revenue − returns) | `mrt_profit_daily` |
| Stock | `sum(stock_end)` in the last snapshot of each account's latest day; WB per card (`nm_id`, sizes summed), Ozon per SKU; available units (Ozon `present − reserved`) | `mrt_stock_daily` |
| Average daily sales | units sold over the last N **full** days / N (days without sales count) | `mrt_supply_planning_daily` |
| CR to cart / order | `adds_to_cart / views`, `orders / views` (0 when no views) | `mrt_funnel_daily` |
| ACOS | `cost / revenue` (0 when no revenue); over a period `sum(cost) / sum(revenue)`, never an average of daily ratios | `mrt_ads_daily` |
| ROMI | `(revenue − cost) / cost` (0 when no cost) | `mrt_ads_daily` |
| Turnover days | `stock_end / avg_daily_sales` over the last 14 full days | insights trigger |
| ABC class | cumulative revenue share over the last 60 full days: A ≤ 80 %, B ≤ 95 %, C rest | `mrt_abc_xyz_analysis` |
| XYZ class | coefficient of variation of the **weekly** quantity over the last 8 full weeks, weeks without sales counted: X < 10 %, Y < 25 %, Z rest | `mrt_abc_xyz_analysis` |
| Break-even price | cost + logistics + commission share | `mrt_breakeven_daily` |

### Finance

Every money movement of a day is in one category, signed from the seller's side (income +,
charges −), and the categories add up to `net_accrued` — what the marketplace added to the
balance that day (`common/finance.py`):

`sales + returns + commission + acquiring + logistics + reverse_logistics + storage +
acceptance + penalties + other = net_accrued`

- **Ozon**: `/v1/finance/balance` for one day at a time gives the breakdown, `accrued`,
  `payments` and the opening/closing balance; `opening + net_accrued + payouts = closing`
  holds for every day. Service names map to categories in `OZON_SERVICE_CATEGORIES`; an
  unknown service goes to `other` and stays visible by name in `details`.
- **WB**: realization report lines; per line `net_accrued = ±forPay − deliveryService −
  paidStorage − paidAcceptance − deduction − penalty + additionalPayment`, which is the
  report's "Итого к оплате" (`bankPaymentSum`). WB publishes no payout history and keeps
  reports from 2025-01-01; the current balance and the amount to withdraw come from the
  balance widget (`/api/v1/account/balance`), snapshotted hourly.
- "Goods after commission" (`mrt_sales_daily.payout`) is **not** what is paid out: it comes
  before logistics, storage and every other charge. The payout is `net_accrued`.

### Why Ozon sales come from the accruals

The posting list is an order list: a posting stays `delivered` after the buyer returns it,
cancelled postings never sold, and its date is the order date. The realization accruals
(`/v1/finance/accrual/by-day`, category `POSTING`) carry the day of the sale, its reversal
for a return and the actual commission. An accrual without a commission block is a later
logistics charge and is not a sale. Ozon orders (`stg_orders`) still come from the postings.

## Time

- **Business day** = Moscow day: `stg_*.day` is `toDate(ts, 'Europe/Moscow')`, and marts
  and task windows use `toDate(now(), 'Europe/Moscow')`, independent of the server's `TZ`.
- `stg_*` timestamps are true instants. The transforms read them from the payload: WB sends
  Moscow wall-clock without an offset, Ozon sends UTC with `Z`.
- `raw_*` timestamp columns keep the collectors' historical convention: the parsers pass naive
  datetimes that the client stores through the process time zone (the same `TZ` as the
  server). WB columns therefore hold Moscow wall-clock, Ozon columns and snapshot times UTC
  wall-clock. Watermarks rely on this, so it is not changed in place; read raw times through
  the payload or `toDateTime(toString(col), 'UTC' | 'Europe/Moscow')`.

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
