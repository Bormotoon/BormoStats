# TODO.md — Self‑hosted Marketplace Analytics (WB + Ozon) — MAX PACK

## 0) One‑pager

Система для self‑hosted аналитики продавца Wildberries + Ozon:
- ingestion (WB/Ozon API) → raw ClickHouse
- transforms (raw → stg) → витрины (stg → mrt)
- FastAPI для метрик/админки
- Metabase для BI
- automation rules (yaml) + actions (Telegram сейчас; позже — цены/реклама/поставки)

Ограничение: только данные своего кабинета (без конкурентов и категорий).

Важно:
- `✅` у секции означает, что спецификация для реализации в todo прописана достаточно подробно; это не равно фактической готовности кода.
- Реальный прогресс вести по чек-листам этапов и acceptance criteria в конце файла.
- Для аудита реализации использовать статусы:
  - `[x]` есть в коде и явно реализовано
  - `[~]` реализовано частично, упрощённо или не проверено end-to-end
  - `[ ]` в репозитории не найдено

---

## 1) Стек и зависимости (только OSS) ✅

### Runtime
- Python 3.12+
- FastAPI + Uvicorn
- Celery + Redis (broker+locks)
- ClickHouse (аналитическое хранилище)
- Metabase (BI)

### Python библиотеки (requirements)
- fastapi
- uvicorn[standard]
- pydantic>=2
- pydantic-settings
- httpx
- tenacity (retry/backoff)
- clickhouse-connect (или clickhouse-driver, но лучше connect)
- redis
- celery
- python-dateutil
- pytz / zoneinfo
- orjson
- structlog (или стандартный logging JSON)
- PyYAML
- pytest, pytest-asyncio
- ruff, black, mypy

---

## 2) Репозиторий и структура ✅

Создать монорепо:

```
marketplace-analytics/
  backend/
    app/
      main.py
      api/
        v1/
          sales.py
          stocks.py
          funnel.py
          ads.py
          kpis.py
          admin.py
      core/
        config.py
        logging.py
        deps.py
      db/
        ch.py
        queries/
          sales.sql
          ...
      services/
        metrics_service.py
        admin_service.py
    Dockerfile
  workers/
    app/
      celery_app.py
      beat_schedule.py
      tasks/
        wb_collect.py
        ozon_collect.py
        transforms.py
        marts.py
        maintenance.py
      utils/
        locking.py
        watermarks.py
        chunking.py
    Dockerfile
  collectors/
    wb/
      client.py
      endpoints.py
      parsers.py
    ozon/
      client.py
      endpoints.py
      parsers.py
    common/
      http_client.py
      retry.py
      time.py
      redaction.py
  warehouse/
    migrations/
      0001_init.sql
      0002_stg.sql
      0003_marts.sql
    apply_migrations.py
    ddl/
      README.md
  automation/
    engine.py
    rules/
      low_stock.yml
      bad_acos.yml
      no_sales_7d.yml
    actions/
      base.py
      telegram.py
  infra/
    docker/
      docker-compose.yml
      clickhouse/
        initdb/
          001_users.sql
        users.xml (optional)
        config.xml (optional)
      metabase/
        plugins/ (optional)
      nginx/ (optional)
  scripts/
    bootstrap.sh
    backfill.py
    run_local.sh
    check_tokens.py
  .env.example
  README.md
  docs/
    architecture.md
    metabase.md
    troubleshooting.md
  Makefile
```

---

## 3) ENV конфигурация (.env.example) ✅

```dotenv
# General
APP_ENV=prod
LOG_LEVEL=INFO
TZ=Europe/Warsaw

# ClickHouse
CH_HOST=clickhouse
CH_PORT=8123
CH_USER=admin
CH_PASSWORD=admin_password
CH_DB=mp_analytics

# ClickHouse read-only user for Metabase (optional)
CH_RO_USER=metabase_ro
CH_RO_PASSWORD=metabase_ro_password

# Redis
REDIS_URL=redis://redis:6379/0

# WB
WB_TOKEN_STATISTICS=...
WB_TOKEN_ANALYTICS=...

# Ozon
OZON_CLIENT_ID=...
OZON_API_KEY=...
# optional perf api key if separate
OZON_PERF_API_KEY=...

# Admin API access
ADMIN_API_KEY=change_me

# Telegram
TG_BOT_TOKEN=
TG_CHAT_ID=
```

---

## 4) Docker Compose (infra/docker/docker-compose.yml) ✅

Требования:
- volume для ClickHouse
- healthchecks
- отдельные контейнеры: backend, worker, beat, metabase

```yaml
version: "3.9"

services:
  clickhouse:
    image: clickhouse/clickhouse-server:latest
    container_name: mp_clickhouse
    ports:
      - "8123:8123"
      - "9000:9000"
    environment:
      - TZ=${TZ:-Europe/Warsaw}
    volumes:
      - ch_data:/var/lib/clickhouse
      - ./clickhouse/initdb:/docker-entrypoint-initdb.d:ro
      # optional configs:
      # - ./clickhouse/config.xml:/etc/clickhouse-server/config.d/config.xml:ro
      # - ./clickhouse/users.xml:/etc/clickhouse-server/users.d/users.xml:ro
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8123/ping | grep -q Ok"]
      interval: 10s
      timeout: 5s
      retries: 12

  redis:
    image: redis:7-alpine
    container_name: mp_redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 12

  backend:
    build:
      context: ../../
      dockerfile: backend/Dockerfile
    container_name: mp_backend
    env_file:
      - ../../.env
    depends_on:
      clickhouse:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

  worker:
    build:
      context: ../../
      dockerfile: workers/Dockerfile
    container_name: mp_worker
    env_file:
      - ../../.env
    depends_on:
      clickhouse:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=4"]

  beat:
    build:
      context: ../../
      dockerfile: workers/Dockerfile
    container_name: mp_beat
    env_file:
      - ../../.env
    depends_on:
      clickhouse:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: ["celery", "-A", "app.celery_app:celery_app", "beat", "--loglevel=INFO"]

  metabase:
    image: metabase/metabase:latest
    container_name: mp_metabase
    ports:
      - "3000:3000"
    environment:
      - MB_DB_FILE=/metabase-data/metabase.db
      - JAVA_TIMEZONE=${TZ:-Europe/Warsaw}
      # If plugins needed:
      # - MB_PLUGINS_DIR=/plugins
    volumes:
      - metabase_data:/metabase-data
      # Optional plugin dir:
      # - ./metabase/plugins:/plugins:ro
    depends_on:
      clickhouse:
        condition: service_healthy

volumes:
  ch_data:
  redis_data:
  metabase_data:
```

---

## 5) ClickHouse: миграции и схема (warehouse/migrations) ✅

### 5.1 Механика миграций
- Таблица `sys_schema_migrations` хранит применённые версии
- `warehouse/apply_migrations.py`:
  - читает `warehouse/migrations/*.sql` по порядку
  - применяет best effort и пишет запись в sys table
  - логирует duration и ошибки
- `scripts/bootstrap.sh` вызывает apply_migrations

### 5.2 ClickHouse initdb (infra/docker/clickhouse/initdb/001_users.sql)

```sql
CREATE DATABASE IF NOT EXISTS mp_analytics;

-- Note: users обычно через users.xml; здесь минимум.
SET allow_experimental_object_type = 1;
```

### 5.3 warehouse/migrations/0001_init.sql (SYS + RAW)

```sql
USE mp_analytics;

-- SYS
CREATE TABLE IF NOT EXISTS sys_schema_migrations
(
  version String,
  applied_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (version);

CREATE TABLE IF NOT EXISTS sys_watermarks
(
  source LowCardinality(String),
  account_id LowCardinality(String),
  watermark_ts DateTime,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (source, account_id);

CREATE TABLE IF NOT EXISTS sys_task_runs
(
  task_name LowCardinality(String),
  run_id UUID,
  started_at DateTime,
  finished_at DateTime,
  status LowCardinality(String),
  rows_ingested UInt64,
  message String,
  meta_json String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(started_at)
ORDER BY (task_name, started_at, run_id);

-- DIMS
CREATE TABLE IF NOT EXISTS dim_marketplace
(
  marketplace LowCardinality(String),
  title String
)
ENGINE = TinyLog;

INSERT INTO dim_marketplace (marketplace, title) VALUES ('wb','Wildberries'),('ozon','Ozon');

CREATE TABLE IF NOT EXISTS dim_account
(
  account_id LowCardinality(String),
  marketplace LowCardinality(String),
  title String,
  created_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (marketplace, account_id);

INSERT INTO dim_account (account_id, marketplace, title) VALUES ('default','wb','WB default'),('default','ozon','Ozon default');

CREATE TABLE IF NOT EXISTS dim_product
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  chrt_id Nullable(UInt64),
  sku Nullable(String),
  offer_id Nullable(String),
  ozon_product_id Nullable(UInt64),
  title Nullable(String),
  brand Nullable(String),
  category Nullable(String),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (marketplace, account_id, product_id);

-- RAW WB
CREATE TABLE IF NOT EXISTS raw_wb_sales
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  srid String,
  last_change_ts DateTime,
  event_ts DateTime,
  nm_id UInt64,
  chrt_id UInt64,
  barcode Nullable(String),
  quantity UInt16,
  price_rub Float64,
  payout_rub Nullable(Float64),
  is_return UInt8,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_ts)
ORDER BY (account_id, srid);

CREATE TABLE IF NOT EXISTS raw_wb_orders
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  srid String,
  last_change_ts DateTime,
  event_ts DateTime,
  nm_id UInt64,
  chrt_id UInt64,
  quantity UInt16,
  price_rub Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_ts)
ORDER BY (account_id, srid);

CREATE TABLE IF NOT EXISTS raw_wb_stocks
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  snapshot_ts DateTime,
  nm_id Nullable(UInt64),
  chrt_id UInt64,
  sku Nullable(String),
  warehouse_id Nullable(UInt64),
  amount Int32,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (account_id, snapshot_ts, chrt_id);

CREATE TABLE IF NOT EXISTS raw_wb_funnel_daily
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  nm_id UInt64,
  open_card_count UInt64,
  add_to_cart_count UInt64,
  orders_count UInt64,
  orders_sum_rub Float64,
  buyouts_count UInt64,
  buyouts_sum_rub Float64,
  cancel_count UInt64,
  cancel_sum_rub Float64,
  add_to_cart_conv Float64,
  cart_to_order_conv Float64,
  buyout_percent Float64,
  add_to_wishlist UInt64,
  currency LowCardinality(String),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, nm_id);

-- RAW OZON
CREATE TABLE IF NOT EXISTS raw_ozon_postings
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  posting_number String,
  status LowCardinality(String),
  created_at DateTime,
  in_process_at Nullable(DateTime),
  shipped_at Nullable(DateTime),
  delivered_at Nullable(DateTime),
  canceled_at Nullable(DateTime),
  ozon_warehouse_id Nullable(UInt64),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (account_id, posting_number);

CREATE TABLE IF NOT EXISTS raw_ozon_posting_items
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  posting_number String,
  ozon_product_id UInt64,
  offer_id Nullable(String),
  name Nullable(String),
  quantity UInt16,
  price Float64,
  payout Nullable(Float64),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(ingested_at)
ORDER BY (account_id, posting_number, ozon_product_id);

CREATE TABLE IF NOT EXISTS raw_ozon_stocks
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  snapshot_ts DateTime,
  ozon_product_id UInt64,
  offer_id Nullable(String),
  warehouse_id Nullable(UInt64),
  present Int32,
  reserved Int32,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (account_id, snapshot_ts, ozon_product_id, warehouse_id);

CREATE TABLE IF NOT EXISTS raw_ozon_ads_daily
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  campaign_id String,
  impressions UInt64,
  clicks UInt64,
  cost Float64,
  orders UInt64,
  revenue Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, campaign_id);

CREATE TABLE IF NOT EXISTS raw_ozon_finance_ops
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  operation_id String,
  operation_ts DateTime,
  type LowCardinality(String),
  amount Float64,
  currency LowCardinality(String),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(operation_ts)
ORDER BY (account_id, operation_ts, operation_id);
```

### 5.4 warehouse/migrations/0002_stg.sql (STG)

```sql
USE mp_analytics;

CREATE TABLE IF NOT EXISTS stg_sales
(
  event_ts DateTime,
  day Date MATERIALIZED toDate(event_ts),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  order_id String,
  posting_number Nullable(String),
  srid Nullable(String),
  product_id String,
  nm_id Nullable(UInt64),
  ozon_product_id Nullable(UInt64),
  offer_id Nullable(String),
  qty Int32,
  price_gross Float64,
  payout Nullable(Float64),
  is_return UInt8,
  last_change_ts Nullable(DateTime),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, order_id, product_id, event_ts);

CREATE TABLE IF NOT EXISTS stg_orders
(
  event_ts DateTime,
  day Date MATERIALIZED toDate(event_ts),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  order_id String,
  status LowCardinality(String),
  product_id Nullable(String),
  qty Nullable(Int32),
  price_gross Nullable(Float64),
  last_change_ts Nullable(DateTime),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, order_id, event_ts);

CREATE TABLE IF NOT EXISTS stg_stocks
(
  snapshot_ts DateTime,
  day Date MATERIALIZED toDate(snapshot_ts),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  ozon_product_id Nullable(UInt64),
  offer_id Nullable(String),
  warehouse_id Nullable(UInt64),
  amount Int32,
  reserved Nullable(Int32),
  present Nullable(Int32),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id, warehouse_id);

CREATE TABLE IF NOT EXISTS stg_funnel_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  views UInt64,
  adds_to_cart UInt64,
  orders UInt64,
  orders_sum Float64,
  buyouts UInt64,
  cancels UInt64,
  add_to_cart_conv Float64,
  cart_to_order_conv Float64,
  buyout_percent Float64,
  wishlist UInt64,
  currency LowCardinality(String),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id);

CREATE TABLE IF NOT EXISTS stg_ads_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  campaign_id String,
  impressions UInt64,
  clicks UInt64,
  cost Float64,
  orders UInt64,
  revenue Float64,
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, campaign_id);
```

### 5.5 warehouse/migrations/0003_marts.sql (MRT + views)

```sql
USE mp_analytics;

CREATE TABLE IF NOT EXISTS mrt_sales_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  qty Int64,
  revenue Float64,
  payout Nullable(Float64),
  returns_qty Int64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id);

CREATE TABLE IF NOT EXISTS mrt_stock_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  warehouse_id Nullable(UInt64),
  stock_end Int64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id, warehouse_id);

CREATE TABLE IF NOT EXISTS mrt_funnel_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  views UInt64,
  adds_to_cart UInt64,
  orders UInt64,
  cr_order Float64,
  cr_cart Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id);

CREATE TABLE IF NOT EXISTS mrt_ads_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  campaign_id String,
  impressions UInt64,
  clicks UInt64,
  cost Float64,
  orders UInt64,
  revenue Float64,
  acos Float64,
  romi Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, campaign_id);

CREATE VIEW IF NOT EXISTS v_kpi_sales_30d AS
SELECT
  marketplace,
  account_id,
  sum(revenue) AS revenue_30d,
  sum(qty) AS qty_30d,
  sum(returns_qty) AS returns_30d
FROM mrt_sales_daily
WHERE day >= today() - 30
GROUP BY marketplace, account_id;

CREATE VIEW IF NOT EXISTS v_kpi_ads_30d AS
SELECT
  marketplace,
  account_id,
  sum(cost) AS cost_30d,
  sum(revenue) AS revenue_30d,
  if(sum(revenue)=0, 0, sum(cost)/sum(revenue)) AS acos_30d
FROM mrt_ads_daily
WHERE day >= today() - 30
GROUP BY marketplace, account_id;
```

---

## 6) Watermarks и locking (workers/app/utils) ✅

### 6.1 sys_watermarks
- get_watermark(source, account_id) → DateTime (UTC) default: now()-48h
- set_watermark(source, account_id, new_ts) только если new_ts больше текущего

### 6.2 Redis locks
- lock ключи: `lock:{source}:{account_id}`
- TTL 10–30 минут
- гарантировать один collector на источник/аккаунт

---

## 7) Celery: приложение и расписание ✅

### 7.1 Celery app config
- broker = REDIS_URL
- task_routes:
  - wb_* → queue wb
  - ozon_* → queue ozon
  - transform_* → queue etl
  - mart_* → queue etl
  - automation_* → queue automation

### 7.2 Beat расписание (workers/app/beat_schedule.py)

```python
from celery.schedules import crontab

beat_schedule = {
  "wb_sales_incremental": {"task": "tasks.wb_collect.wb_sales_incremental", "schedule": crontab(minute="*/15")},
  "wb_orders_incremental": {"task": "tasks.wb_collect.wb_orders_incremental", "schedule": crontab(minute="*/15")},
  "wb_stocks_snapshot": {"task": "tasks.wb_collect.wb_stocks_snapshot", "schedule": crontab(minute="*/30")},
  "wb_funnel_roll": {"task": "tasks.wb_collect.wb_funnel_roll", "schedule": crontab(minute="5", hour="*/1")},

  "wb_sales_backfill_14d": {"task": "tasks.wb_collect.wb_sales_backfill_days", "schedule": crontab(minute="10", hour="3")},
  "wb_orders_backfill_14d": {"task": "tasks.wb_collect.wb_orders_backfill_days", "schedule": crontab(minute="20", hour="3")},
  "wb_funnel_backfill_14d": {"task": "tasks.wb_collect.wb_funnel_backfill_days", "schedule": crontab(minute="30", hour="3")},

  "ozon_postings_incremental": {"task": "tasks.ozon_collect.ozon_postings_incremental", "schedule": crontab(minute="*/20")},
  "ozon_stocks_snapshot": {"task": "tasks.ozon_collect.ozon_stocks_snapshot", "schedule": crontab(minute="*/30")},
  "ozon_ads_daily": {"task": "tasks.ozon_collect.ozon_ads_daily", "schedule": crontab(minute="40", hour="*/6")},

  "transform_raw_to_stg": {"task": "tasks.transforms.transform_all_recent", "schedule": crontab(minute="*/30")},
  "build_marts_recent": {"task": "tasks.marts.build_marts_recent", "schedule": crontab(minute="0", hour="*/1")},
  "build_marts_backfill_14d": {"task": "tasks.marts.build_marts_backfill_days", "schedule": crontab(minute="0", hour="4")},

  "automation_rules_run": {"task": "tasks.maintenance.run_automation_rules", "schedule": crontab(minute="0", hour="9,15,21")},
  "maintenance_prune_raw": {"task": "tasks.maintenance.prune_old_raw", "schedule": crontab(minute="0", hour="2")},
}
```

---

## 8) MART builds: SQL шаблоны ✅

### 8.1 mrt_sales_daily
```sql
INSERT INTO mrt_sales_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  sum(qty) AS qty,
  sumIf(price_gross * qty, is_return=0) AS revenue,
  sum(payout) AS payout,
  sumIf(qty, is_return=1) AS returns_qty,
  now() AS updated_at
FROM stg_sales
WHERE day >= today() - 14
GROUP BY day, marketplace, account_id, product_id;
```

### 8.2 mrt_stock_daily
```sql
INSERT INTO mrt_stock_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  warehouse_id,
  argMax(amount, snapshot_ts) AS stock_end,
  now() AS updated_at
FROM stg_stocks
WHERE day >= today() - 14
GROUP BY day, marketplace, account_id, product_id, warehouse_id;
```

### 8.3 mrt_funnel_daily
```sql
INSERT INTO mrt_funnel_daily
SELECT
  day,
  marketplace,
  account_id,
  product_id,
  sum(views) AS views,
  sum(adds_to_cart) AS adds_to_cart,
  sum(orders) AS orders,
  if(sum(views)=0, 0, sum(orders)/sum(views)) AS cr_order,
  if(sum(views)=0, 0, sum(adds_to_cart)/sum(views)) AS cr_cart,
  now() AS updated_at
FROM stg_funnel_daily
WHERE day >= today() - 14
GROUP BY day, marketplace, account_id, product_id;
```

### 8.4 mrt_ads_daily
```sql
INSERT INTO mrt_ads_daily
SELECT
  day,
  marketplace,
  account_id,
  campaign_id,
  sum(impressions) AS impressions,
  sum(clicks) AS clicks,
  sum(cost) AS cost,
  sum(orders) AS orders,
  sum(revenue) AS revenue,
  if(sum(revenue)=0, 0, sum(cost)/sum(revenue)) AS acos,
  if(sum(cost)=0, 0, (sum(revenue)-sum(cost))/sum(cost)) AS romi,
  now() AS updated_at
FROM stg_ads_daily
WHERE day >= today() - 60
GROUP BY day, marketplace, account_id, campaign_id;
```

---

## 9) Backend (FastAPI) — endpoints ✅

### 9.1 Health
- GET /health
- GET /ready

### 9.2 Read-only API
- GET /api/v1/sales/daily
- GET /api/v1/stocks/current
- GET /api/v1/funnel/daily
- GET /api/v1/ads/daily
- GET /api/v1/kpis

### 9.3 Admin (ADMIN_API_KEY)
- GET /api/v1/admin/watermarks
- POST /api/v1/admin/run-task
- POST /api/v1/admin/backfill
- GET /api/v1/admin/task-runs

---

## 10) Automation ✅

### 10.1 YAML rules
- automation/rules/low_stock.yml
- automation/rules/bad_acos.yml
- automation/rules/no_sales_7d.yml

### 10.2 Engine
- load rules
- run CH query
- eval condition expr
- execute actions

### 10.3 Telegram action
- sendMessage via HTTPS

---

## 11) Metabase: SQL queries (dashboards/sql) ✅

1) Sales Overview
```sql
SELECT day, sum(revenue) revenue, sum(qty) qty, sum(returns_qty) returns
FROM mrt_sales_daily
WHERE day BETWEEN {{from}} AND {{to}}
GROUP BY day
ORDER BY day;
```

2) Top products 30d
```sql
SELECT product_id, sum(revenue) revenue, sum(qty) qty
FROM mrt_sales_daily
WHERE day >= today() - 30
GROUP BY product_id
ORDER BY revenue DESC
LIMIT 50;
```

3) Funnel
```sql
SELECT day, product_id, views, adds_to_cart, orders, cr_order, cr_cart
FROM mrt_funnel_daily
WHERE day BETWEEN {{from}} AND {{to}}
ORDER BY day, product_id;
```

4) Stocks yesterday
```sql
SELECT marketplace, product_id, sum(stock_end) stock_end
FROM mrt_stock_daily
WHERE day = today() - 1
GROUP BY marketplace, product_id
ORDER BY stock_end ASC;
```

5) Ads
```sql
SELECT day, campaign_id, cost, revenue, acos, romi
FROM mrt_ads_daily
WHERE day BETWEEN {{from}} AND {{to}}
ORDER BY day, campaign_id;
```

6) KPI 30d
```sql
SELECT * FROM v_kpi_sales_30d;
```

---

## 12) Bootstrap, smoke checks и служебные скрипты ✅

### 12.1 `scripts/bootstrap.sh`
- поднимает `docker compose up -d`
- ждёт healthcheck ClickHouse и Redis
- запускает `warehouse/apply_migrations.py`
- проверяет наличие `sys_watermarks`, `sys_task_runs`, `dim_*`
- при необходимости создаёт read-only пользователя для Metabase
- запускает `scripts/check_tokens.py`
- завершает работу с non-zero exit code, если инфраструктура или токены невалидны

### 12.2 `scripts/check_tokens.py`
- проверяет `WB_TOKEN_STATISTICS` на базовом statistics endpoint
- проверяет `WB_TOKEN_ANALYTICS` на analytics endpoint
- проверяет `OZON_CLIENT_ID` + `OZON_API_KEY` на seller API
- если `OZON_PERF_API_KEY` не задан, пишет warning, но не валит bootstrap
- sanitizes логи: не печатать токены и полные headers

### 12.3 `scripts/backfill.py`
- ручной запуск backfill по источнику: `wb_sales`, `wb_orders`, `wb_funnel`, `ozon_postings`, `ozon_finance`, `ozon_ads`
- параметры: `--account-id`, `--days`, `--date-from`, `--date-to`, `--dry-run`
- пишет запись в `sys_task_runs`

---

## 13) Shared HTTP/SDK слой и ограничения API ✅

### 13.1 `collectors/common/http_client.py`
- единый `httpx` клиент с timeout `connect/read/write`
- retry policy:
  - WB `429` обрабатывать по `X-Ratelimit-Retry` / `X-Ratelimit-Reset`
  - Ozon `429` и `5xx` обрабатывать через exponential backoff + jitter
- простой circuit breaker после серии ошибок на endpoint
- логировать `request_id`, `marketplace`, `endpoint`, `status_code`, `duration_ms`
- bodies логировать только в усечённом виде и без секретов

### 13.2 Время, watermark и late-arriving data
- все даты и watermark хранить в UTC
- для WB `dateFrom` переводить из MSK (`UTC+3`) в UTC перед сохранением watermark
- разделять `event_ts`, `last_change_ts`, `snapshot_ts`, `ingested_at`
- watermark обновлять только после успешной вставки в raw
- late-arriving данные покрывать rolling backfill окнами, а не только инкрементом

### 13.3 Ограничения API, которые надо закодировать явно
- WB statistics:
  - `/api/v1/supplier/sales` обновляется примерно раз в 30 минут
  - хранение на стороне WB гарантировано не более 90 дней
  - `flag=0` использовать для инкремента по `lastChangeDate`
  - `flag=1` использовать для полного пересбора конкретного дня
- WB analytics:
  - funnel обновляется раз в час
  - возвраты и отмены могут приходить с привязкой к дню исходного заказа
  - нужен hourly roll + daily backfill окна
- Ozon:
  - часть analytics / premium-возможностей может быть недоступна
  - такие ошибки должны деградировать мягко: warning + skip, а не падение всего пайплайна

### 13.4 Product mapping и унификация идентификаторов
- заполнение `dim_product` из WB и Ozon raw/stg
- единый `product_id`:
  - WB: детерминированно из `nm_id` или `chrt_id`
  - Ozon: детерминированно из `ozon_product_id` или `offer_id`
- хранить исходные идентификаторы отдельно, не теряя первичный marketplace key

---

## 14) Collectors: Wildberries — детальный implementation backlog ✅

### 14.1 Auth и конфиг
- env:
  - `WB_TOKEN_STATISTICS`
  - `WB_TOKEN_ANALYTICS`
  - optional `WB_TOKEN_CREATED_AT`
- отдельные клиенты/методы для statistics и analytics API
- при старте backend/worker уметь валидировать токены через admin smoke-check
- если задан `WB_TOKEN_CREATED_AT`, считать reminder за 14 дней до истечения 180-дневного TTL

### 14.2 `wb_sales_incremental`
- источник: `/api/v1/supplier/sales`
- расписание: каждые 10-15 минут
- читать watermark `wb_sales_last_change_ts`
- вызывать с `dateFrom=watermark`, `flag=0`
- сохранять raw payload + выделенные ключи
- дедуп делать по `account_id + srid`, версионность по `ingested_at` / `last_change_ts`
- watermark двигать на `max(last_change_ts)` только после успешной вставки всей пачки

### 14.3 `wb_sales_backfill_days`
- расписание: 1 раз в сутки
- окно: последние 7-14 дней
- вызывать `flag=1` по каждому дню отдельно
- пересобирать raw и затем stg/mart за эти дни
- использовать для компенсации late updates, возвратов и исправлений WB

### 14.4 `wb_orders_incremental` и `wb_orders_backfill_days`
- делать по той же схеме, что и sales, если orders endpoint реально используется
- если в целевой версии продукта orders решено не брать, это должно быть зафиксировано в README и beat schedule
- не оставлять "полумёртвую" таблицу/задачу без документации

### 14.5 `wb_stocks_snapshot`
- собирать остатки каждые 30-60 минут
- хранить snapshot-подходом с `snapshot_ts`
- stg должен уметь агрегировать остатки по складу и по товару
- отдельно контролировать пустые ответы: это либо "нулевые остатки", либо ошибка источника

### 14.6 `wb_funnel_roll` и `wb_funnel_backfill_days`
- источник: `/api/analytics/v3/sales-funnel/products`
- hourly roll по последним 7 дням
- daily backfill по последним 14 дням
- throttling по account/source, чтобы не выбивать лимиты analytics API
- документировать, что `orders`/`buyouts`/`cancels` в funnel не равны фактической cash-выручке

### 14.7 Ошибки и chunking
- крупные окна разбивать на чанки по дням
- при частичном падении повторять только неуспешный chunk
- записывать run status и row counts в `sys_task_runs`

---

## 15) Collectors: Ozon — детальный implementation backlog ✅

### 15.1 Auth и базовый клиент
- все запросы отправлять с `Client-Id` и `Api-Key`
- базовый URL держать конфигурируемым
- предусмотреть capability flags по аккаунту:
  - `has_finance`
  - `has_ads`
  - `has_premium_analytics`

### 15.2 `ozon_postings_incremental`
- собирать postings/orders как обязательный минимум
- поддержать схему продавца FBO/FBS, если API отдаёт эти режимы отдельно
- watermark по `last_changed` / `since` в зависимости от endpoint
- raw хранить отдельно для postings и posting items
- stg нормализовать до `stg_orders` и `stg_sales` там, где можно восстановить продажу/возврат

### 15.3 `ozon_stocks_snapshot`
- снимок остатков каждые 30-60 минут
- хранить остатки по складам и offer/product
- проверять отрицательные или аномально большие значения как data-quality warning

### 15.4 `ozon_finance_incremental`
- желательно включить в базовый backlog, потому что без него нет нормальной unit economics
- собирать операции/начисления/удержания в `raw_ozon_finance_ops`
- нормализовать комиссии, логистику, штрафы, выплаты в отдельные поля `stg_sales` или вспомогательный finance stg
- расписание: минимум 1 раз в сутки, лучше каждые 6 часов

### 15.5 `ozon_ads_daily`
- daily или 6-hourly выгрузка рекламной статистики
- idempotent upsert по `account_id + day + campaign_id`
- при отсутствии `OZON_PERF_API_KEY` задача должна автоматически отключаться, а не падать

### 15.6 Premium/недоступные методы
- ошибки "method unavailable", "premium required", "forbidden for account" обрабатывать как `skip_with_warning`
- capability сохранять в `sys_task_runs.meta_json` или отдельной service-config таблице
- UI/admin endpoint должен показывать, что источник отключён из-за недоступной функции, а не из-за сбоя

---

## 16) Observability, security и data quality ✅

### 16.1 Логи и метрики
- structured JSON logs для backend и workers
- поля: `request_id`, `task_id`, `run_id`, `marketplace`, `account_id`, `endpoint`, `duration_ms`, `rows_ingested`, `status`
- если включён Prometheus:
  - `ingestion_requests_total{marketplace,endpoint,status}`
  - `ingestion_rows_total{table}`
  - `task_duration_seconds{task}`
  - `watermark_lag_seconds{source}`
  - `empty_payload_total{source}`

### 16.2 Алерты и operational signals
- watermark lag > threshold
- task failures > 0 за окно
- ClickHouse disk usage > threshold
- repeated empty responses по источнику, где обычно есть данные
- токен скоро истекает

### 16.3 Security minimum
- `ADMIN_API_KEY` обязателен для админ-эндпоинтов
- Metabase подключать через read-only ClickHouse user
- reverse proxy/TLS опционален, но желателен для prod
- в логах и ошибках не показывать токены, ключи, полные auth headers

### 16.4 Data quality checks
- контроль дублей в raw и stg
- контроль пропущенных дней в `mrt_sales_daily`, `mrt_stock_daily`, `mrt_funnel_daily`, `mrt_ads_daily`
- аномалии row-count по сравнению с предыдущими днями
- отдельный maintenance task: prune/ttl для raw, если объём начинает расти слишком быстро

---

## 17) Тестирование ✅

### 17.1 Unit tests
- парсеры ответов WB/Ozon на fixtures JSON
- time normalization: UTC/MSK, `dateFrom`, watermark updates
- retry/backoff policy и redaction
- automation rules: condition eval, action dispatch, templating

### 17.2 Integration tests
- поднять `clickhouse + redis`
- прогнать migrations
- загрузить raw fixtures
- выполнить transforms и mart builds
- проверить read-only API FastAPI против тестового ClickHouse

### 17.3 Contract / recorded tests
- режим `record` для живых ответов API с удалением чувствительных данных
- режим `replay` для CI без реальных токенов
- fixtures версионировать по marketplace и endpoint

### 17.4 Smoke tests
- `scripts/bootstrap.sh` в dev-режиме
- `/health`, `/ready`, admin auth
- один ручной backfill в `--dry-run`

---

## 18) CI/CD ✅

### 18.1 GitHub Actions pipeline
- lint: `ruff`, `black --check`, `mypy`
- tests: `pytest`
- build Docker images для `backend` и `worker`
- проверка, что migrations применяются на чистой ClickHouse-инстанции

### 18.2 Optional release flow
- tagged releases
- optional push в GHCR
- changelog / release notes

### 18.3 Secrets policy
- CI не должен требовать боевых WB/Ozon токенов
- recorded fixtures использовать вместо реальных API-вызовов
- `.env` и любые ключи не коммитить

---

## 19) Документация ✅

### 19.1 `README.md`
- что делает система и что не делает
- быстрый старт
- какие токены нужны WB и Ozon
- как поднять Metabase
- как включить Telegram alerts
- как выполнить ручной backfill
- troubleshooting: `429`, invalid key, empty data, late data

### 19.2 `docs/architecture.md`
- схема модулей
- поток данных `raw -> stg -> mrt`
- расписание задач
- источники watermarks и lock-keys

### 19.3 `docs/metabase.md`
- как подключить ClickHouse
- как импортировать SQL questions / dashboards
- какие дашборды считаются обязательными

### 19.4 `docs/troubleshooting.md`
- что делать при зависшем watermark
- что делать при 429/5xx
- как пересобрать витрины за период
- как проверить capability/доступность Ozon методов

---

## 20) Аудит состояния проекта (2026-03-05)

### 20.1 Что уже есть в репозитории
- `[x]` Скелет монорепы: `backend`, `workers`, `collectors`, `warehouse`, `automation`, `dashboards`, `infra`, `scripts`, `docs`
- `[x]` Базовая инфраструктура: `.env.example`, `Makefile`, Dockerfiles, `docker-compose.yml`
- `[x]` ClickHouse слой: migrations, `apply_migrations.py`, `sys_*`, `raw_*`, `stg_*`, `mrt_*`, SQL views
- `[x]` Worker слой: Celery app, beat schedule, watermarks, Redis locks, `sys_task_runs`
- `[x]` Collectors: WB sales/orders/stocks/funnel, Ozon postings/stocks/ads
- `[x]` Ozon finance: есть collector `ozon_finance_incremental/backfill` + raw/stg pipeline для `finance_ops`
- `[x]` Ozon capability degradation: premium/forbidden методы помечаются как `skipped` с причиной в `sys_task_runs.meta_json`, пайплайн не падает
- `[x]` Product mapping sync: `dim_product` синхронизируется из WB/Ozon raw в transform pipeline
- `[x]` ELT: `raw -> stg` transforms и `stg -> mrt` builds
- `[x]` Backend API: `/health`, `/ready`, read-only endpoints, admin endpoints с `X-API-Key`
- `[x]` Automation: YAML rules engine + Telegram action + scheduled run task
- `[x]` BI assets: SQL-шаблоны для Metabase

### 20.2 Что реализовано частично
- `[x]` `scripts/bootstrap.sh`: поднимает compose, ждёт health, применяет миграции, проверяет таблицы, делает token/API smoke checks
- `[x]` `scripts/check_tokens.py`: проверяет env и выполняет реальные API smoke-checks для WB/Ozon (с мягкой деградацией по Ozon Perf)
- `[x]` Shared HTTP layer: реализованы timeout policy, WB/Ozon retry handling (включая 429), circuit breaker, redaction и structured request logging
- `[x]` WB backfill: реализован дневной режим `flag=1` по дням с отдельной задачей и обновлением watermark
- `[x]` WB orders backfill: реализован отдельный дневной backfill `flag=1` по дням, а не только инкремент
- `[x]` WB funnel: hourly roll работает на скользящем 7-дневном окне, backfill поддерживает период до 365 дней с чанкингом
- `[x]` Ozon postings/orders: добавлены пагинация, агрегированный сбор по схемам `fbs/fbo` и дедупликация по posting number
- `[x]` Observability: есть `sys_task_runs`, JSON logging, `/metrics` endpoint и базовые Prometheus counters/gauges/histograms в workers
- `[x]` Документация расширена до целевой спецификации: README + architecture + metabase + troubleshooting

### 20.3 Что пока отсутствует
- `[x]` End-to-end верификация acceptance criteria (локальный technical pass; без боевых WB/Ozon токенов)

### 20.4 Что удалось проверить локально в ходе аудита
- `[x]` `python3 -m compileall backend workers collectors automation warehouse scripts` проходит
- `[x]` `docker compose --env-file .env -f infra/docker/docker-compose.yml config` проходит, предупреждение про `version` устранено
- `[x]` `. .venv/bin/activate && pytest -q` проходит (`9 passed`)

---

## 21) План работ по этапам ✅

### Этап A — skeleton + infra
- [x] структура репо
- [x] `.env.example`
- [x] `docker-compose`
- [x] bootstrap и smoke checks
- [x] `/health` и `/ready`

### Этап B — ClickHouse + service layer
- [x] migrations `sys/raw/stg/mrt`
- [x] `apply_migrations.py`
- [x] `http_client.py`, retry, redaction, time utils
- [x] watermarks, locks, `sys_task_runs`

### Этап C — WB ingestion
- [x] auth + token checks
- [x] sales incremental
- [x] sales backfill 7-14d
- [x] orders incremental/backfill or explicit exclusion
- [x] stocks snapshot
- [x] funnel hourly + backfill

### Этап D — Ozon ingestion
- [x] postings/orders
- [x] stocks snapshot
- [x] finance ops
- [x] ads daily
- [x] premium/capability degradation

### Этап E — ELT + marts + API
- [x] raw -> stg transforms
- [x] stg -> mrt builds
- [x] KPI/query endpoints
- [x] admin endpoints

### Этап F — BI + automation
- [x] Metabase queries/dashboards
- [x] YAML rules
- [x] Telegram action
- [x] scheduled rule runs

### Этап G — quality + release
- [x] observability
- [x] tests
- [x] CI/CD
- [x] docs
- [x] final acceptance pass

---

## 22) Acceptance Criteria ✅

- [x] `docker compose up -d` поднимает backend, worker, beat, clickhouse, redis, metabase
- [x] `scripts/bootstrap.sh` проходит на валидной конфигурации (`BOOTSTRAP_SKIP_TOKEN_CHECKS=1` для dry-run без боевых токенов)
- [~] WB sales минимум за последние 7-14 дней подтягиваются и сохраняются в ClickHouse
- [~] Ozon postings/stocks подтягиваются и сохраняются в ClickHouse
- [~] transforms и marts строятся повторяемо и без дублей
- [x] backend отдаёт данные из `mrt_*`
- [~] Metabase показывает минимум 5-6 базовых дашбордов
- [~] Telegram алерты реально приходят
- [~] повторный запуск ingestion не плодит дубли
- [x] при `429` WB/Ozon система корректно ждёт и продолжает работу (покрыто unit-тестами retry + заголовков WB)
- [x] недоступные Ozon premium-методы не валят весь пайплайн (покрыто unit-тестами capability деградации)
