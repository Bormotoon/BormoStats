# Metabase Setup

## Start

Metabase is included in `docker-compose` and is available at `http://localhost:3000`.

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

Create one Metabase question per file, then build dashboards.
