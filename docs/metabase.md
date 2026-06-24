# Metabase Setup

## Start

Metabase is included in `docker-compose` and is available at `http://localhost:13000` by default.
You can change it with `METABASE_HOST_PORT` in `.env`.

## Connect ClickHouse

Use ClickHouse connection details:

- Host: `clickhouse`
- Port: `8123`
- DB: `mp_analytics`
- User/Password: from `.env`

For read-only access create and use `CH_RO_USER` / `CH_RO_PASSWORD`.

## SQL cards

Prepared SQL templates are in `dashboards/sql`:

1. `01_sales_overview.sql`
2. `02_top_products_30d.sql`
3. `03_funnel.sql`
4. `04_stocks_yesterday.sql`
5. `05_ads.sql`
6. `06_kpi_30d.sql`
7. `07_finance_ops_daily.sql`

Create one Metabase question per file, then build dashboards.

## Dashboard baseline

Use `dashboards/manifest.yml` as source of truth for required dashboards and card composition.

Minimum dashboard set:

1. Sales Overview
2. Funnel
3. Stocks
4. Ads
5. KPI
6. Finance

## Recommended setup flow

1. Connect ClickHouse in Metabase using read-only user.
2. Create SQL questions from all files in `dashboards/sql`.
3. Group cards into dashboards according to `dashboards/manifest.yml`.
4. Save dashboard filters (`from`, `to`, `marketplace`, `account_id`) where applicable.
5. Validate cards against API output for same period and account.
