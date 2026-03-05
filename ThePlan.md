Ниже — **готовый TODO.md** (можешь просто скопировать целиком и отдать GPT-5.3-Codex). Я специально сделал так, чтобы по нему можно было **реально “в лоб” собрать систему**: сбор данных WB+Ozon → ClickHouse → витрины/метрики → Metabase → автоматизация/уведомления.

---

# TODO.md — Self-hosted Marketplace Analytics (WB + Ozon)

## 0) Цель и границы проекта

### Цель

Сделать self-hosted систему аналитики для **своего** магазина на Wildberries и Ozon:

* регулярный сбор данных (продажи/заказы/остатки/финансы/реклама/воронка)
* хранение истории и быстрые агрегации
* API для доступа к метрикам
* BI-дашборды (Metabase)
* задел под автоматизацию (rules + actions) и уведомления (Telegram)

### Не цель (не делать в рамках базовой реализации)

* аналитика конкурентов, категории, чужие продажи, глобальные тренды (это не даёт seller API)
* скрейпинг витрины маркетплейсов (можно добавить потом как отдельный модуль)

---

## 1) Ключевые факты по API (учесть в реализации)

### Wildberries (WB)

* Авторизация: API-токен в заголовке `Authorization`. Токен действует **180 дней**. Есть разные типы токенов; для self-hosted on-premise подходит personal token, но его нельзя передавать третьим лицам. ([WB API][1])
* Rate limit: при 429 WB отдаёт заголовки `X-Ratelimit-*` (Retry/Reset/Limit) — реализовать корректный backoff. ([WB API][1])
* Отчёты продаж/возвратов (statistics-api): `/api/v1/supplier/sales`. Данные обновляются **каждые 30 минут**. Хранение гарантируется **не более 90 дней** — значит нужен регулярный сбор и своё хранилище. Для идентификации заказа использовать поле `srid`. ([WB API][2])
* Параметры `dateFrom` + `flag` (в reports):

  * `flag=0` → инкремент по `lastChangeDate` (много строк, до ~80k)
  * `flag=1` → выгрузка за конкретную дату (полный срез дня) ([WB API][2])
* Воронка/аналитика карточек: `/api/analytics/v3/sales-funnel/products`. Обновляется **раз в час**; часть событий может догружаться позже. Возвраты/отмены отображаются днём заказа (важно для интерпретации). Максимум периодов — **до 365 дней**. ([WB API][3])
* В аналитике WB есть отдельные лимиты на методы (учесть throttling и очереди). ([WB API][3])
* Таймзона в reports: время в параметрах указывается в **МСК (UTC+3)** — все даты хранить в UTC, а конвертировать на выводе. ([WB API][2])

### Ozon

* Старт работы: продавец генерирует **Client ID и API key** и использует их в запросах к Seller API. ([docs.ozon.ru][4])
* Performance API: через внешний API можно собирать статистику по рекламе/каналам и оптимизировать ставки (закладываем модуль ads). ([docs.ozon.ru][5])
* В аналитике есть ограничения/часть возможностей может зависеть от подписки (Premium) — код должен уметь “мягко деградировать”, если какие-то методы недоступны. ([pkg.go.dev][6])

---

## 2) Технологический стек (только OSS / self-hosted)

### Обязательное

* **Python 3.12+**
* **FastAPI** (HTTP API, админ-эндпоинты, health)
* **ClickHouse** (основное хранилище фактов и витрин)
* **Redis** (broker/lock/cache)
* **Celery** (workers) + Celery Beat (scheduler)
* **Metabase** (BI)

### Рекомендуемое

* **Alembic** не нужен (ClickHouse), но миграции через SQL-файлы + версионирование
* **Ruff + Black + MyPy**
* **pytest**
* **Prometheus + Grafana** (мониторинг) — опционально, но желательно

---

## 3) Репозиторий и структура

Создать монорепу:

```
marketplace-analytics/
  backend/                  # FastAPI
  workers/                  # Celery tasks (collect/transform)
  collectors/               # API-клиенты WB/Ozon + нормализация
  warehouse/                # схемы ClickHouse + миграции + витрины
  dashboards/               # метаданные Metabase (экспорт/импорт) + инструкции
  automation/               # rules engine + actions (telegram и т.д.)
  infra/
    docker/
      docker-compose.yml
      nginx/ (optional)
  scripts/                  # утилиты: backfill, reindex, bootstrap
  docs/
  .env.example
  README.md
```

### Стандарты

* Всё конфигурирование через env (`.env`), секреты не коммитить
* Логи structured JSON
* Идемпотентность ingestion: повторные запуски не плодят дубли

---

## 4) Инфраструктура Docker (docker-compose)

### 4.1 docker-compose services

* `clickhouse` (+ volume)
* `redis` (+ volume)
* `backend` (FastAPI)
* `worker` (Celery worker)
* `beat` (Celery beat)
* `metabase` (+ volume)
* (optional) `prometheus`, `grafana`
* (optional) `caddy` или `nginx` для reverse proxy + TLS

### 4.2 .env.example (обязательные переменные)

* Общие:

  * `APP_ENV=prod|dev`
  * `LOG_LEVEL=INFO`
  * `TZ=Europe/Warsaw`
* ClickHouse:

  * `CH_HOST`, `CH_PORT`, `CH_USER`, `CH_PASSWORD`, `CH_DB`
* Redis:

  * `REDIS_URL=redis://redis:6379/0`
* WB:

  * `WB_TOKEN_*` (минимум токен статистики + токен analytics категории)
* Ozon:

  * `OZON_CLIENT_ID`
  * `OZON_API_KEY`
  * (optional) `OZON_PERF_API_KEY`
* Telegram (опционально, но задел сразу):

  * `TG_BOT_TOKEN`
  * `TG_CHAT_ID`

### 4.3 Bootstrap script

Скрипт `scripts/bootstrap.sh`:

* поднимает compose
* ждёт доступность ClickHouse/Redis
* применяет schema migrations в ClickHouse
* создаёт “watermarks” таблицы
* делает smoke-test API клиентов (проверяет токены и базовые эндпоинты)

---

## 5) ClickHouse: модели данных

### 5.1 Принципы

* Слой `raw_*` — сырые данные “как пришло”, минимум преобразований
* Слой `stg_*` — нормализация (типизация, унификация полей)
* Слой `mrt_*` — витрины/агрегаты для графиков и API

Использовать движки:

* `MergeTree` / `ReplacingMergeTree` (для upsert-подобного поведения)
* Партиционирование по `toYYYYMM(date)` или `toDate(event_ts)`
* Индексы по ключам (product_id, order_id, marketplace, account_id)

### 5.2 Базовые сущности (минимум)

1. `dim_marketplace` (wb/ozon)
2. `dim_account` (на будущее: несколько кабинетов/токенов)
3. `dim_product` (nmId/sku/offer_id и т.д.)

### 5.3 RAW таблицы (минимальный набор)

* `raw_wb_sales` (из `/api/v1/supplier/sales`)
* `raw_wb_orders` (аналогичный reports orders endpoint, если используешь)
* `raw_wb_stocks` (остатки)
* `raw_wb_sales_funnel` (из analytics sales-funnel)
* `raw_ozon_postings` (заказы/отправления)
* `raw_ozon_stocks`
* `raw_ozon_finance` (финансовые отчёты/движение)
* `raw_ozon_ads_stats` (Performance API)

**Во всех raw:** хранить `payload String` (JSON) + извлечённые ключи (order_id/product_id/event_ts/last_change_ts).

### 5.4 STG таблицы (нормализованные факты)

* `stg_sales` (унифицированные продажи wb+ozon)
* `stg_orders`
* `stg_stocks`
* `stg_ads_daily`
* `stg_funnel_daily`

Единый набор колонок (пример для `stg_sales`):

* `event_ts` (UTC)
* `marketplace` (Enum: wb/ozon)
* `account_id`
* `order_id`
* `product_id`
* `qty`
* `price_gross`
* `discount_pct`
* `payout` (если есть)
* `is_return`
* `warehouse`
* `region`
* `last_change_ts`
* `source` (endpoint/version)

### 5.5 MART витрины (агрегаты)

* `mrt_sales_daily` (day, marketplace, product_id, revenue, qty, returns, payout, profit_est)
* `mrt_sales_hourly` (опционально)
* `mrt_stock_daily` (day, product_id, stock_end, stock_avg)
* `mrt_ads_daily` (day, campaign_id, impressions, clicks, cost, orders, revenue, acos, romi)
* `mrt_funnel_daily` (day, product_id, views, adds_to_cart, orders, cr_cart, cr_order)

---

## 6) HTTP клиенты и общий SDK слой

### 6.1 Общий HTTP слой

Сделать библиотеку `collectors/http_client.py`:

* таймауты (connect/read)
* retry policy:

  * 429:

    * для WB использовать `X-Ratelimit-Retry` и `X-Ratelimit-Reset` ([WB API][1])
    * для Ozon — экспоненциальный backoff + jitter
  * 5xx: retry limited
* circuit breaker (простая реализация)
* логирование request_id, endpoint, latency, status_code
* redaction секретов в логах

### 6.2 Нормализация времени

* все timestamps сохранять в UTC
* WB `dateFrom` и примеры указывают МСК (UTC+3) — при инкрементах правильно конвертировать и хранить watermark в UTC ([WB API][2])

---

## 7) Collectors: Wildberries

### 7.1 WB auth и токены

* реализовать конфиг токенов:

  * `WB_TOKEN_STATISTICS`
  * `WB_TOKEN_ANALYTICS`
* валидация токенов на старте
* напоминание: токен живёт 180 дней → добавить “token expiry reminder” (по дате создания в конфиге, если пользователь задаст) ([WB API][1])

### 7.2 Сбор sales (обязательный)

Источник: `/api/v1/supplier/sales` (statistics-api) ([WB API][2])
Задачи:

* `task_wb_sales_incremental` каждые 10–15 минут:

  * читает watermark (`wb_sales_last_change_ts`)
  * вызывает endpoint с `dateFrom=watermark` и `flag=0`
  * сохраняет в `raw_wb_sales`
  * обновляет watermark на max(lastChangeDate)
* `task_wb_sales_daily_backfill` раз в сутки:

  * для последних N дней (например 7–14) запрашивает `flag=1` по дням
  * пересобирает raw за день (ReplacingMergeTree по уникальному ключу)
* Учесть, что хранение на стороне WB гарантировано только 90 дней → регулярный сбор обязателен. ([WB API][2])
* Дедупликация: использовать `srid` как идентификатор заказа/строки (и другие ключи из ответа). ([WB API][2])

### 7.3 Сбор orders (желательно)

(Если используешь endpoint orders в том же разделе reports) — сделать аналогично sales: incremental + daily backfill по `dateFrom/flag`. ([WB API][2])

### 7.4 Сбор stocks (обязательный)

* реализовать сбор остатков (endpoint из “work with products” / stocks)
* расписание: каждые 30–60 минут
* сохранить в `raw_wb_stocks` и нормализовать в `stg_stocks`

### 7.5 Сбор funnel analytics (обязательный)

Источник: `/api/analytics/v3/sales-funnel/products` ([WB API][3])
Задачи:

* `task_wb_funnel_daily` раз в час:

  * период: последние 7 дней (скользящее окно) + “чтобы догружались хвосты”
  * группировка по продуктам
  * сохранять raw и stg
* Учесть:

  * обновление раз в час ([WB API][3])
  * возвраты/отмены отображаются по дню заказа → правильно трактовать метрики (документировать) ([WB API][3])
  * период макс 365 дней ([WB API][3])
  * лимиты на запросы — сделать throttling по аккаунту ([WB API][3])

---

## 8) Collectors: Ozon

### 8.1 Auth

* все запросы должны включать `Client-Id` и `Api-Key` в headers ([docs.ozon.ru][4])
* реализовать `OzonClient` с базовым URL `api-seller.ozon.ru` (конфигурируемо)

### 8.2 Заказы/отправления (обязательный минимум)

* реализовать сбор списка postings (FBO/FBS — в зависимости от схемы продавца)
* инкремент:

  * watermark по `since`/`last_changed` (что доступно у метода)
* raw → stg_orders

### 8.3 Stocks (обязательный)

* собирать остатки по складам
* raw → stg_stocks

### 8.4 Finance (желательно, но сильно повышает ценность)

* сбор финансовых отчётов/движения денег
* нормализация комиссий/логистики/выплат в stg (по возможностям API)

### 8.5 Analytics (опционально)

* реализовать модуль аналитики (если доступно)
* если метод возвращает “недоступно без Premium”, сервис не падает, а пишет предупреждение и продолжает по остальным задачам ([pkg.go.dev][6])

### 8.6 Ads (Performance API) — задел

* модуль `ozon_perf_ads`:

  * сбор daily stats: impressions/clicks/cost/orders/revenue
  * сохранить в `raw_ozon_ads_stats`, затем в `stg_ads_daily`
* Performance API позиционируется для сбора статистики и оптимизации ставок ([docs.ozon.ru][5])

---

## 9) ETL/ELT: преобразования и витрины

### 9.1 Raw → Stg

Сделать `workers/tasks_transform.py`:

* `transform_wb_sales_to_stg`
* `transform_wb_stocks_to_stg`
* `transform_wb_funnel_to_stg`
* `transform_ozon_orders_to_stg`
* `transform_ozon_stocks_to_stg`
* `transform_ozon_finance_to_stg`
* `transform_ozon_ads_to_stg`

Требования:

* типизация чисел/дат
* нормализация product_id (создать mapping)
* хранить `source_endpoint` и `ingested_at`

### 9.2 Stg → Mart

Сделать задачи агрегации:

* `build_mrt_sales_daily` (ежечасно + ежедневный пересчёт последних 14 дней)
* `build_mrt_ads_daily` (ежедневно)
* `build_mrt_funnel_daily` (ежечасно)
* `build_mrt_stock_daily` (ежедневно)

Метрики:

* Revenue, Qty, Returns
* CR: orders/views, cart_adds/views
* ACOS = cost / revenue (если revenue>0)
* ROMI = (revenue - cost) / cost (если cost>0)
* Profit_est (если доступны комиссии/логистика; иначе оставить NULL и добавить “manual cost model” позже)

---

## 10) Backend (FastAPI): API для себя

### 10.1 Базовые эндпоинты

* `GET /health`
* `GET /ready`
* `GET /metrics` (если Prometheus)

### 10.2 Данные и метрики

* `GET /api/v1/sales/daily?from=YYYY-MM-DD&to=...&marketplace=...&product_id=...`
* `GET /api/v1/products` (список товаров/маппинг)
* `GET /api/v1/stocks/current`
* `GET /api/v1/funnel/daily`
* `GET /api/v1/ads/daily`
* `GET /api/v1/kpis?period=7d|30d` (общие KPI)

### 10.3 Админ-эндпоинты

* `POST /api/v1/admin/run-task` (ручной запуск Celery задачи)
* `GET /api/v1/admin/watermarks`
* `POST /api/v1/admin/backfill` (параметры marketplace+days)

Безопасность:

* минимально: Basic Auth или API key для админки (env `ADMIN_API_KEY`)
* если ставишь reverse proxy — можно ограничить IP

---

## 11) Metabase (BI)

### 11.1 Подключение

* Подключить Metabase к ClickHouse (проверить способ подключения в контейнере: драйвер/плагин)
* Создать набор “Questions” и “Dashboards”:

  1. Sales Overview (7/30/90 дней)
  2. Product Performance (top/bottom)
  3. Funnel (views → cart → orders)
  4. Stocks (остатки и дни покрытия)
  5. Ads (ACOS/ROMI)

### 11.2 Репликация настроек

* зафиксировать инструкции экспорта/импорта Metabase (или хранить SQL-шаблоны запросов в `dashboards/`)
* описать ручные шаги в `docs/metabase.md`

---

## 12) Automation engine (минимальный, но рабочий)

### 12.1 Rules DSL

Сделать YAML правила в `automation/rules/*.yml`:

Примеры правил:

* `low_stock_alert`:

  * условие: `stock_end < threshold`
  * действие: telegram notify
* `ads_bad_acos`:

  * условие: `acos > 0.40` AND `cost > X`
  * действие: telegram notify
* `no_sales_7d`:

  * условие: `sales_qty_7d == 0`
  * действие: telegram notify

### 12.2 Engine

* загрузка YAML
* вычисление условий (на основе mart таблиц)
* выполнение actions (пока только Telegram)
* запуск по расписанию 1–4 раза в день

### 12.3 Actions интерфейс

`automation/actions/base.py`:

* `send_telegram(message, severity, context)`
* заглушки на будущее:

  * `update_price(...)`
  * `pause_ads_campaign(...)`
  * `create_supply_task(...)`

---

## 13) Telegram уведомления

* реализовать модуль `automation/telegram.py`
* шаблоны сообщений:

  * 📦 Остатки заканчиваются: товар, остаток, дней покрытия
  * 🔥 Товар растёт: revenue +% WoW
  * ⚠️ Реклама убыточна: ACOS, cost, revenue

---

## 14) Надёжность, идемпотентность, качество данных

### 14.1 Watermarks

Таблица `sys_watermarks` в ClickHouse:

* `source` (wb_sales, wb_funnel, ozon_postings, ...)
* `account_id`
* `watermark_ts_utc`
* `updated_at`

### 14.2 Дедупликация

* raw таблицы: `ReplacingMergeTree` с `version=ingested_at`
* stg таблицы: ключи `(marketplace, account_id, order_id, product_id, event_ts)` и т.п.

### 14.3 Backfill стратегия

* ежедневный пересчёт последних 14 дней для витрин
* WB daily `flag=1` на последние 7–14 дней (скользящее окно)
* хранить “ingestion lag” метрику (на сколько часов отстаём)

---

## 15) Observability

### 15.1 Логи

* JSON логи (request_id, task_id, marketplace, endpoint, duration_ms, rows_ingested)

### 15.2 Метрики (если Prometheus)

* `ingestion_requests_total{marketplace,endpoint,status}`
* `ingestion_rows_total{table}`
* `task_duration_seconds{task}`
* `watermark_lag_seconds{source}`

### 15.3 Алёрты (опционально)

* watermark lag > N часов
* task failures > 0
* ClickHouse disk usage > threshold

---

## 16) Тестирование

### 16.1 Unit tests

* парсинг ответов WB/Ozon (fixtures JSON)
* нормализация времени и чисел
* правила automation engine (условия)

### 16.2 Integration tests (docker-compose)

* поднять clickhouse+redis
* прогнать transform на тестовых raw fixtures
* проверить, что витрины строятся и запросы возвращают данные

### 16.3 Контрактные “recorded” тесты (опционально)

* режим “record” для реальных API ответов (с удалением персональных данных)
* режим “replay” для CI

---

## 17) CI/CD (GitHub Actions)

* lint: ruff, black --check, mypy
* tests: pytest
* build docker images
* (опционально) push в GHCR
* release tags

---

## 18) Документация (обязательная)

`README.md`:

* что это
* требования
* быстрый старт
* как получить токены WB (какие нужны категории)
* как получить Ozon Client-Id/Api-Key
* как открыть Metabase и подключиться
* как включить Telegram уведомления
* troubleshooting (429, invalid key, пустые данные)

`docs/architecture.md`:

* схема модулей
* таблицы clickhouse (raw/stg/mrt)
* расписание задач

---

## 19) План работ по этапам (как чек-лист релиза)

### Этап A — Скелет + инфраструктура

* [ ] Создать структуру репо
* [ ] docker-compose: clickhouse/redis/backend/worker/beat/metabase
* [ ] bootstrap script + .env.example
* [ ] health/ready endpoints

### Этап B — WB ingestion

* [ ] WB HTTP client + rate-limit handling (X-Ratelimit-*) ([WB API][1])
* [ ] WB sales incremental + watermarks ([WB API][2])
* [ ] WB sales daily backfill (flag=1) ([WB API][2])
* [ ] WB stocks collector
* [ ] WB funnel collector (hourly + rolling window) ([WB API][3])

### Этап C — Ozon ingestion

* [ ] Ozon client (Client-Id/Api-Key headers) ([docs.ozon.ru][4])
* [ ] postings/orders collector
* [ ] stocks collector
* [ ] finance collector (если доступно)
* [ ] ads collector (Performance API module) ([docs.ozon.ru][5])

### Этап D — Нормализация и витрины

* [ ] raw → stg transforms
* [ ] stg → mart aggregates
* [ ] KPI endpoints в FastAPI

### Этап E — Metabase

* [ ] подключение к ClickHouse
* [ ] 5 основных дашбордов
* [ ] docs по импорту/экспорту

### Этап F — Автоматизация

* [ ] rules YAML + engine
* [ ] telegram actions
* [ ] расписание rule runs

### Этап G — Надёжность

* [ ] retry/backoff везде
* [ ] идемпотентность + дедуп
* [ ] мониторинг + метрики (опционально)
* [ ] CI

---

## 20) Acceptance Criteria (готово, если…)

* [ ] Система поднимается одной командой `docker compose up -d`
* [ ] WB sales за последние 7–14 дней подтягиваются и сохраняются в ClickHouse
* [ ] Ozon orders/stocks подтягиваются и сохраняются в ClickHouse
* [ ] Витрина `mrt_sales_daily` строится и отдаёт корректные суммы по дням
* [ ] Metabase показывает минимум 3 дашборда (Sales/Funnel/Stocks)
* [ ] Telegram уведомление о низких остатках реально приходит
* [ ] Повторный запуск ingestion не плодит дубли
* [ ] При 429 WB система корректно ждёт и продолжает (не DDOS’ит API) ([WB API][1])

---

Если хочешь, я ещё добавлю в этот TODO **готовые DDL для ClickHouse (raw/stg/mrt)** и шаблоны Celery задач/расписания (beat), чтобы Codex вообще не гадал, а просто “копировал и собирал”.

[1]: https://dev.wildberries.ru/en/docs/openapi/api-information "Documentation — WB API"
[2]: https://dev.wildberries.ru/en/openapi/reports "Documentation — WB API"
[3]: https://dev.wildberries.ru/en/docs/openapi/analytics "Documentation — WB API"
[4]: https://docs.ozon.ru/global/en/api/intro/?utm_source=chatgpt.com "How to Work with API"
[5]: https://docs.ozon.ru/global/en/api/perfomance-api/?utm_source=chatgpt.com "Performance API | Ozon Help"
[6]: https://pkg.go.dev/github.com/diphantxm/ozon-api-client/ozon?utm_source=chatgpt.com "ozon package - github.com/diphantxm/ozon-api-client/ozon"
