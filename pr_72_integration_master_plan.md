# Мастер-план интеграции PR #72 в BormoStats (Runbook для агента Gemini 3.8 Flash)

> **Целевой исполнитель:** ИИ-агент `Gemini 3.8 Flash` (или разработчик-мейнтейнер)  
> **Репозиторий:** `Bormotoon/BormoStats` (ветка `main`)  
> **Источник изменений:** PR [#72 — Ozon analytics customization: article economics, funnel and daily P&L](https://github.com/Bormotoon/BormoStats/pull/72) (ветка `codex/svoyo-upstream-review`)

---

## 0. Системный протокол для агента Gemini 3.8 Flash (ПРОЧИТАТЬ ПЕРЕД ВЫПОЛНЕНИЕМ)

Ты работаешь с production-репозиторием `BormoStats`. В проекте действуют строгие автоматические проверки CI. Нарушение любого из 6 правил ниже приведёт к гарантированному падению тестов.

### Правило 1. Два пакета с именем `app` (`backend/app` и `workers/app`)
* Бэкенд и воркеры имеют собственные пакеты `app` и **не могут** импортироваться в одном процессе Python одновременно.
* Общий код между ними размещается **только** в пакете `common/` или `collectors/`.
* Запуск тестов воркеров всегда выполняется с `BORMOSTATS_TEST_TARGET=workers PYTHONPATH=workers:. pytest tests/worker_suite -q`.

### Правило 2. Синтаксис параметров ClickHouse и защита `FakeClickHouse`
* В `tests/fakes.py` класс `FakeClickHouse` проверяет каждый SQL-запрос регулярным выражением `r"\{(\w+):([^{}]+)\}"`.
* Если в SQL используется серверный биндинг `{param_name:Type}`, в словарь `parameters` **обязан** передаваться ключ `param_name`.
* **ЗАПРЕЩЕНО** использовать Python `.format()` на строках, содержащих `{param:Type}`. Для генерации `INSERT ... VALUES` используй только хелпер `common.sql.insert_values_sql(table, columns)`.

### Правило 3. Временные зоны и типы дат
* Все `DateTime` значения, передаваемые в ClickHouse из Python, должны быть **timezone-aware UTC** с обнулёнными микросекундами:
  ```python
  from datetime import UTC, datetime


  def utc_now() -> datetime:
      return datetime.now(UTC).replace(microsecond=0)
  ```
* Бизнес-день в аналитике — всегда **московский день** (`toDate(..., 'Europe/Moscow')`).

### Правило 4. Контракт миграций ClickHouse (`warehouse/apply_migrations.py`)
* В ветке `main` уже существуют миграции **`0001`–`0043`** (`0039`–`0043` заняты Яндекс Маркетом).
* Все новые миграции из PR #72 должны создаваться строго с номерами **`0044`–`0050`**.
* Каждая миграция `warehouse/migrations/00XX_name.sql` **обязана** иметь парный файл отката `warehouse/migrations/rollbacks/00XX_name.sql`.
* Скрипт `apply_migrations.py` после выполнения миграции проверяет (`verify_postconditions`), что все таблицы из `CREATE TABLE` и колонки из `ALTER TABLE ... ADD COLUMN` реально существуют в БД.

### Правило 5. Инвариант архивации `STAT_SPECS` и `prune_old_raw`
* Каждая новая таблица `raw_*` (кроме конкурентов, SERP и ручного импорта) **обязана** быть добавлена в:
  1. `workers/app/utils/history_archive.py` $\rightarrow$ словарь `STAT_SPECS`.
  2. `workers/app/tasks/maintenance.py` $\rightarrow$ список `tables` в функции `prune_old_raw`.
  3. `tests/integration/conftest.py` $\rightarrow$ кортеж `TRUNCATE_TABLES`.
  4. `tests/worker_suite/test_history_store.py` $\rightarrow$ обновить ожидаемое число таблиц в `test_prune_is_unchanged_when_history_is_disabled`.

### Правило 6. Поддержка трёх маркетплейсов (`wb`, `ozon`, `ym`)
* Во всех регулярных выражениях FastAPI Query/Path и моделях Pydantic используй паттерн `r"^(wb|ozon|ym)$"` (кроме эндпоинтов, специфичных исключительно для Ozon, например `/api/v1/funnel/ozon`).

---

## 1. Сводная матрица дефектов PR #72 и конфликтов с `main`

### 1.1. Конфликты между PR #72 и актуальным `main`

| ID | Конфликт | Файлы в `main` | Как исправляем в этом плане |
|---|---|---|---|
| **M-1** | Номера миграций `0039`–`0043` заняты Яндекс Маркетом | `warehouse/migrations/0039..0043` | Перенумеровываем миграции PR #72 в **`0044`–`0050`**. |
| **M-2** | Таблицы PR #72 названы без префиксов (`ozon_realization_reports` и т.д.) | `workers/app/utils/history_archive.py` | Переименовываем в `raw_ozon_realization_reports`, `raw_ozon_sku_ad_reports`, `raw_ozon_cis_buyouts`, `raw_ozon_campaigns`, `raw_ozon_funnel_import`, `sys_ozon_report_jobs`. |
| **M-3** | Падение тестов архивации истории и очистки `raw_*` | `test_pipeline_smoke.py`, `test_history_store.py` | Регистрируем новые таблицы в `STAT_SPECS`, `prune_old_raw` и `TRUNCATE_TABLES`. |
| **M-4** | Отсутствие `ym` в `DailyPnlService` и фильтрах | `backend/app/services/daily_pnl_service.py` | Разрешаем `wb`, `ozon`, `ym` во всех общих сервисах P&L. |
| **M-5** | Дублирование со страницей `Taxes.jsx` в `main` | `frontend/src/pages/Taxes.jsx` | Подключаем `Taxes.jsx` к серверному расчёту налогов из `common/pnl_tax.py`. |
| **M-6** | Падение Playwright E2E (`smoke.spec.js`) под ролью `viewer` | `frontend/src/pages/Dashboard.jsx` | Делаем graceful fallback на `/sales/daily` при `403` от `/pnl/daily`. |

### 1.2. Карта всех 23 замечаний ревью GitHub Copilot

| № | Категория | Файл в PR #72 | Проблема |В каком PR чиним |
|---|---|---|---|---|
| **#1** | RBAC / Security | `backend/app/api/v1/funnel.py` | `/funnel/ozon/related` отдаёт `cost_price_rub` роли `viewer` (`AnalyticsReadAuth`). | **PR #5** |
| **#2** | RBAC / Security | `backend/app/db/queries/stocks.sql` | `/stocks/current` отдаёт `cost_price_rub` и оценку склада роли `viewer`. | **PR #2** |
| **#3** | Frontend Race | `frontend/src/pages/PnL.jsx` | Нет флага отмены (`cancelled`) в `useEffect` при быстрой смене дат. | **PR #3** |
| **#4** | Unit Tests | `tests/unit/test_expense_dates.py` | Тест ожидает старую логику отбрасывания неполных месяцев вместо календарной аллокации. | **PR #3** |
| **#5** | Unit Tests | `tests/unit/test_pnl_tax_service.py` | Мок БД в тесте не обрабатывает запрос к `mrt_finance_daily` в `_apply_financing()`. | **PR #3** |
| **#6** | ClickHouse SQL | `backend/app/api/v1/funnel.py` | В `ORDER BY day, sku, scheme` нет `account_id` $\rightarrow$ недетерминированная пагинация. | **PR #5** |
| **#7** | Worker Crash | `workers/app/tasks/exports.py` | Фоновый CSV-экспорт `stocks_current` падает с `KeyError: 'as_of'`. | **PR #2** |
| **#8** | Multi-account | `article_economics_service.py` | Словарь карточек индексируется по `sku` без `account_id`, перезаписывая себестоимость. | **PR #4** |
| **#9** | CIS Dedup | `article_economics_service.py` | Дедупликация выкупов СНГ обрезана окном `date_from..date_to`. | **PR #4** |
| **#10** | Multi-account Tax | `article_economics_service.py` | Налог одного кабинета (`PNL_TAX_ACCOUNT_ID`) размазывается по всем кабинетам. | **PR #4** |
| **#11** | Tax Status | `article_economics_service.py` | Статус налога остаётся `realization`, даже когда `DailyPnlService` перешёл на `estimated`. | **PR #4** |
| **#12** | CIS Dedup | `daily_pnl_service.py` | Дедупликация выкупов СНГ обрезана окном `date_from..date_to`. | **PR #3** |
| **#13** | CIS Dedup | `ozon_cis_service.py` | Запрос внутренних начислений для дедупликации СНГ ограничен `date_from..date_to`. | **PR #3** |
| **#14** | Missing Cost | `ozon_cis_service.py` | Товар из СНГ без себестоимости получает `cogs = 0`, но не попадает в `missing_costs`. | **PR #3** |
| **#15** | Math Bug | `pnl_service.py` | После корректировки прибыли на СНГ и факторинг не пересчитывается `margin_pct`. | **PR #3** |
| **#16** | CIS Dedup | `pnl_service.py` | Дедупликация выкупов СНГ в месячном P&L обрезана границами периода. | **PR #3** |
| **#17** | Infinite Loop | `collectors/ozon/sku_ad_reports.py` | Упавший `UUID` отчёта (`FAILED`) остаётся в `ozon_report_jobs` и вечно блокирует сбор. | **PR #1** |
| **#18** | Perf $O(N \times S)$ | `common/article_economics.py` | Вызов `self.net()` (обход всех SKU) до и после каждой из $N$ операций начислений. | **PR #4** |
| **#19** | UI False Zero | `frontend/src/pages/Dashboard.jsx` | Пустой массив дней с нулями рисуется как «Прибыль 0 ₽» вместо «Нет данных». | **PR #3** |
| **#20** | RBAC / UI Crash | `frontend/src/pages/Dashboard.jsx` | Перевод дашборда на `/pnl/daily` (`ManagerAuth`) ломает экран для `viewer` и `analyst`. | **PR #3** |
| **#21** | UI Wrong Label | `frontend/src/pages/Dashboard.jsx` | Всегда пишется «после вычета налога», даже для WB/YM или при выключенном налоге. | **PR #3** |
| **#22** | UI Math Mix | `frontend/src/pages/PnL.jsx` | В таблице расходов смешиваются месячная логистика/хранение и суточная реклама/налог. | **PR #3** |
| **#23** | UI State Bug | `frontend/src/pages/PnL.jsx` | Добавление расхода в `ExpenseForm` не обновляет карточки прибыли из `daily`. | **PR #3** |

---

## 2. Подготовка Git-окружения (Выполнить один раз перед стартом)

Выполни в терминале следующие команды, чтобы получить локальную ветку-источник `pr-72-donor`, из которой ты будешь пофайлово собирать 6 чистых PR:

```bash
git checkout main
git pull origin main

# Скачиваем PR #72 в локальную ветку pr-72-donor
git fetch origin pull/72/head:pr-72-donor
```

> **Важно для агента:** Не делай `git merge pr-72-donor` в `main`! Для каждого из 6 PR ниже создавай новую ветку от `main`, забирай нужные файлы через `git show pr-72-donor:<path> > <path>` (или создавай их по эталонным шаблонам ниже) и применяй исправления.

---

## 3. Детальные спецификации 6 Pull Request'ов

---

### PR #1: Сборщики данных Ozon и схема БД (`0044`–`0048`)

**Ветка:** `git checkout -b feat/ozon-extended-collectors main`

#### Шаг 1.1. Создай миграции `0044`–`0048` и скрипты отката

1. **`warehouse/migrations/0044_ozon_realization.sql`**:
```sql
CREATE TABLE IF NOT EXISTS raw_ozon_realization_reports
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  month Date,
  row_number UInt32,
  ozon_product_id UInt64,
  offer_id String,
  seller_price Float64,
  sale_qty UInt32,
  sale_amount Float64,
  sale_commission Float64,
  return_qty UInt32,
  return_amount Float64,
  return_commission Float64,
  net_accrued Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(month)
ORDER BY (account_id, month, row_number, offer_id);
```
*Откат `warehouse/migrations/rollbacks/0044_ozon_realization.sql`:*
```sql
DROP TABLE IF EXISTS raw_ozon_realization_reports;
```

2. **`warehouse/migrations/0045_ozon_sku_ad_reports.sql`**:
```sql
CREATE TABLE IF NOT EXISTS raw_ozon_sku_ad_reports
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  campaign_id String,
  sku UInt64,
  offer_id String DEFAULT '',
  title String DEFAULT '',
  impressions UInt64 DEFAULT 0,
  clicks UInt64 DEFAULT 0,
  cost Float64,
  orders UInt64 DEFAULT 0,
  revenue Float64 DEFAULT 0,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, campaign_id, sku);
```
*Откат `warehouse/migrations/rollbacks/0045_ozon_sku_ad_reports.sql`:*
```sql
DROP TABLE IF EXISTS raw_ozon_sku_ad_reports;
```

3. **`warehouse/migrations/0046_ozon_report_jobs.sql`**:
```sql
CREATE TABLE IF NOT EXISTS sys_ozon_report_jobs
(
  account_id LowCardinality(String),
  report_kind LowCardinality(String),
  period_key String,
  job_uuid String,
  status LowCardinality(String) DEFAULT 'pending',
  error String DEFAULT '',
  payload String DEFAULT '',
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (account_id, report_kind, period_key, job_uuid)
TTL created_at + INTERVAL 30 DAY;
```
*Откат `warehouse/migrations/rollbacks/0046_ozon_report_jobs.sql`:*
```sql
DROP TABLE IF EXISTS sys_ozon_report_jobs;
```

4. **`warehouse/migrations/0047_ozon_cis_buyouts.sql`**:
```sql
CREATE TABLE IF NOT EXISTS raw_ozon_cis_buyouts
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  posting_number String,
  sku UInt64,
  offer_id String,
  product_name String DEFAULT '',
  quantity Int32,
  seller_price Float64,
  amount Float64,
  commission Float64 DEFAULT 0,
  payout Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, posting_number, sku);
```
*Откат `warehouse/migrations/rollbacks/0047_ozon_cis_buyouts.sql`:*
```sql
DROP TABLE IF EXISTS raw_ozon_cis_buyouts;
```

5. **`warehouse/migrations/0048_ozon_campaigns.sql`**:
```sql
CREATE TABLE IF NOT EXISTS raw_ozon_campaigns
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  campaign_id String,
  title String,
  state LowCardinality(String),
  adv_object_type LowCardinality(String),
  daily_budget Float64 DEFAULT 0,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, campaign_id);
```
*Откат `warehouse/migrations/rollbacks/0048_ozon_campaigns.sql`:*
```sql
DROP TABLE IF EXISTS raw_ozon_campaigns;
```

#### Шаг 1.2. Перенеси коллекторы Ozon и исправь вечный цикл ошибок (Copilot #17)

Перенеси из `pr-72-donor` изменения в `collectors/ozon/endpoints.py`, `collectors/ozon/client.py`, `collectors/ozon/parsers.py` и файл `collectors/ozon/sku_ad_reports.py`.

В `collectors/ozon/sku_ad_reports.py` замени все обращения к `ozon_report_jobs` на `sys_ozon_report_jobs` и `ozon_sku_ad_reports` на `raw_ozon_sku_ad_reports`, и **обязательно исправь логику обработки упавших отчётов**:

```python
# В collectors/ozon/sku_ad_reports.py:
TERMINAL_FAILURE_STATES = frozenset({"FAILED", "ERROR", "CANCELLED", "NOT_FOUND"})


def load_active_job(
    ch: Any, account_id: str, report_kind: str, period_key: str
) -> dict[str, Any] | None:
    """Return the latest non-failed job for the period, or None if a new UUID is needed."""
    rows = ch.query(
        "SELECT job_uuid, status, payload FROM sys_ozon_report_jobs FINAL"
        " WHERE account_id = {aid:String} AND report_kind = {kind:String}"
        " AND period_key = {pkey:String}"
        " AND status NOT IN ('failed', 'cancelled')"
        " ORDER BY updated_at DESC LIMIT 1",
        parameters={"aid": account_id, "kind": report_kind, "pkey": period_key},
    ).named_results()
    return next(iter(rows), None)


def save_job_state(
    ch: Any,
    *,
    account_id: str,
    report_kind: str,
    period_key: str,
    job_uuid: str,
    status: str,
    payload: str = "",
    error: str = "",
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    ch.insert(
        "sys_ozon_report_jobs",
        [[account_id, report_kind, period_key, job_uuid, status, error[:500], payload, now, now]],
        column_names=[
            "account_id",
            "report_kind",
            "period_key",
            "job_uuid",
            "status",
            "error",
            "payload",
            "created_at",
            "updated_at",
        ],
    )
```
При поллинге статуса отчёта в Ozon Performance API: если `state.upper() in TERMINAL_FAILURE_STATES`, сначала вызывай `save_job_state(..., status="failed", error=state)`, и только после этого выбрасывай `RuntimeError`. Тогда следующий запуск воркера не возьмёт сломанный `job_uuid`, а запросит новый.

#### Шаг 1.3. Зарегистрируй таблицы в `STAT_SPECS`, `maintenance.py` и `conftest.py`

1. В `workers/app/utils/history_archive.py` добавь в `STAT_SPECS`:
```python
    "raw_ozon_realization_reports": StatSpec(
        "ozon", ("month", "row_number", "offer_id"), "month"
    ),
    "raw_ozon_sku_ad_reports": StatSpec(
        "ozon", ("day", "campaign_id", "sku"), "day"
    ),
    "raw_ozon_cis_buyouts": StatSpec(
        "ozon", ("day", "posting_number", "sku"), "day"
    ),
    "raw_ozon_campaigns": StatSpec(
        "ozon", ("campaign_id",), "ingested_at"
    ),
```
2. В `workers/app/tasks/maintenance.py` в список `tables` внутри `prune_old_raw` добавь:
```python
(("raw_ozon_realization_reports", "month"),)
(("raw_ozon_sku_ad_reports", "day"),)
(("raw_ozon_cis_buyouts", "day"),)
(("raw_ozon_campaigns", "ingested_at"),)
```
3. В `tests/worker_suite/test_history_store.py` в `test_prune_is_unchanged_when_history_is_disabled` обнови ожидаемое количество таблиц с `19` на `23`.
4. В `tests/integration/conftest.py` добавь `raw_ozon_realization_reports`, `raw_ozon_sku_ad_reports`, `raw_ozon_cis_buyouts`, `raw_ozon_campaigns`, `sys_ozon_report_jobs` в `TRUNCATE_TABLES`.

#### Шаг 1.4. Проверка PR #1
```bash
python warehouse/apply_migrations.py verify
ruff check . && ruff format --check .
mypy backend workers collectors automation warehouse scripts common
pytest -q
```

---

### PR #2: Историческая оценка остатков на дату (`as_of`) и защита себестоимости (RBAC)

**Ветка:** `git checkout -b feat/stocks-as-of-valuation main`

#### Шаг 2.1. Обнови `backend/app/db/queries/stocks.sql`
Добавь фильтр `day <= %(as_of)s` в CTE `scoped` и присоединение себестоимости из `v_offer_cost` / `dim_product_cost`:
```sql
WITH scoped AS (
  SELECT day, marketplace, account_id, product_id, warehouse_id, stock_end
  FROM mrt_stock_daily FINAL
  WHERE day <= %(as_of)s
    AND (%(marketplace)s = '' OR marketplace = %(marketplace)s)
    AND (%(account_id)s = '' OR account_id = %(account_id)s)
    AND (marketplace, account_id) IN (
      SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
    )
),
names AS (
  SELECT
    marketplace, account_id, product_id,
    anyLast(title) AS name, anyLast(offer_id) AS article, anyLast(image_url) AS image
  FROM dim_product FINAL
  WHERE title IS NOT NULL
  GROUP BY marketplace, account_id, product_id
),
costs AS (
  SELECT marketplace, account_id, product_id, any(cost_price_rub) AS cost_price_rub
  FROM v_offer_cost
  GROUP BY marketplace, account_id, product_id
),
legacy_costs AS (
  SELECT marketplace, toString(product_id) AS product_id, any(cost_price_rub) AS cost_price_rub
  FROM dim_product_cost FINAL
  GROUP BY marketplace, product_id
),
warehouses AS (
  SELECT 'ozon' AS marketplace, account_id, warehouse_id,
    argMax(JSONExtractString(payload, 1, 'warehouse_name'), snapshot_ts) AS warehouse_name
  FROM raw_ozon_stocks FINAL
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY AND warehouse_id IS NOT NULL
  GROUP BY account_id, warehouse_id
  UNION ALL
  SELECT 'wb' AS marketplace, account_id, toInt64(warehouse_id) AS warehouse_id,
    argMax(JSONExtractString(payload, 1, 'warehouseName'), snapshot_ts) AS warehouse_name
  FROM raw_wb_stocks FINAL
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY AND warehouse_id IS NOT NULL
  GROUP BY account_id, warehouse_id
  UNION ALL
  SELECT 'ym' AS marketplace, account_id, warehouse_id,
    argMax(warehouse_name, snapshot_ts) AS warehouse_name
  FROM raw_ym_stocks FINAL
  WHERE snapshot_ts >= now() - INTERVAL 7 DAY
  GROUP BY account_id, warehouse_id
),
latest AS (
  SELECT marketplace, account_id, max(day) AS current_day
  FROM scoped
  GROUP BY marketplace, account_id
)
SELECT
  s.day AS day,
  s.marketplace AS marketplace,
  s.account_id AS account_id,
  s.product_id AS product_id,
  s.warehouse_id AS warehouse_id,
  multiIf(
    any(w.warehouse_name) != '', any(w.warehouse_name),
    s.warehouse_id IS NULL AND s.marketplace = 'wb', 'Склад WB',
    s.warehouse_id IS NULL AND s.marketplace = 'ym', 'Склад Я.Маркет',
    s.warehouse_id IS NULL, '',
    toString(s.warehouse_id)
  ) AS warehouse_name,
  any(n.name) AS title,
  any(n.article) AS offer_id,
  any(n.image) AS image_url,
  sum(s.stock_end) AS stock_end,
  if(any(c.cost_price_rub) > 0, any(c.cost_price_rub),
     if(any(lc.cost_price_rub) > 0, any(lc.cost_price_rub), NULL)) AS cost_price_rub,
  if(cost_price_rub IS NOT NULL, round(sum(s.stock_end) * cost_price_rub, 2), NULL) AS stock_value_rub
FROM scoped AS s
INNER JOIN latest AS l
  ON s.marketplace = l.marketplace
  AND s.account_id = l.account_id
  AND s.day = l.current_day
LEFT JOIN names AS n
  ON s.marketplace = n.marketplace
  AND s.account_id = n.account_id
  AND s.product_id = n.product_id
LEFT JOIN costs AS c
  ON s.marketplace = c.marketplace
  AND s.account_id = c.account_id
  AND s.product_id = c.product_id
LEFT JOIN legacy_costs AS lc
  ON s.marketplace = lc.marketplace
  AND s.product_id = lc.product_id
LEFT JOIN warehouses AS w
  ON s.marketplace = w.marketplace
  AND s.account_id = w.account_id
  AND ifNull(s.warehouse_id, -1) = w.warehouse_id
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.warehouse_id
ORDER BY stock_end ASC, s.marketplace, s.product_id
LIMIT %(limit)s
OFFSET %(offset)s
```

#### Шаг 2.2. Защити себестоимость в `backend/app/api/v1/stocks.py` (Copilot #2)
В `backend/app/api/v1/stocks.py` добавь параметр `as_of: date | None = Query(default=None)` и скрывай `cost_price_rub` / `stock_value_rub` для ролей ниже `manager`:
```python
from datetime import date, datetime
from zoneinfo import ZoneInfo
from app.models.organization import OrgMemberRole
from fastapi import APIRouter, Depends, Query


@router.get("/current")
def stocks_current(
    *,
    auth: AnalyticsReadAuth,
    filters: ListQueryParams = Depends(get_list_query_params),
    as_of: date | None = Query(default=None),
    client: ChClientDependency,
    cache: QueryCacheDependency,
) -> dict[str, object]:
    resolved_as_of = as_of or datetime.now(ZoneInfo("Europe/Moscow")).date()
    service = MetricsService(client, cache)
    items = service.stocks_current(
        organization_id=auth.organization_id,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        as_of=resolved_as_of,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    if not auth.allows(OrgMemberRole.manager):
        items = [{**row, "cost_price_rub": None, "stock_value_rub": None} for row in items]
    return build_paginated_response(
        items=items,
        limit=filters.limit,
        offset=filters.offset,
        as_of=resolved_as_of.isoformat(),
    )
```
*(Не забудь добавить `as_of: date | None = None` в `MetricsService.stocks_current` в `backend/app/services/metrics_service.py`).*

#### Шаг 2.3. Исправь падение фонового экспорта в `workers/app/tasks/exports.py` (Copilot #7)
В `workers/app/tasks/exports.py` в функции `build_query_parameters`:
```python
if dataset == "stocks_current":
    params["as_of"] = date.fromisoformat(raw["as_of"]) if raw.get("as_of") else date.today()
```

#### Шаг 2.4. Проверка PR #2
```bash
pytest tests/integration/test_sql_contracts.py tests/unit/test_api_auth_matrix.py -q
```

---

### PR #3: Датированные расходы (`0049`), Налоги, СНГ/Факторинг и Daily P&L

**Ветка:** `git checkout -b feat/daily-pnl-and-taxes main`

#### Шаг 3.1. Создай миграцию `0049_additional_expenses_dates.sql` (+ rollback)
* **`warehouse/migrations/0049_additional_expenses_dates.sql`**:
```sql
ALTER TABLE dim_additional_expense ADD COLUMN IF NOT EXISTS expense_date Nullable(Date);
```
* **`warehouse/migrations/rollbacks/0049_additional_expenses_dates.sql`**:
```sql
ALTER TABLE dim_additional_expense DROP COLUMN IF EXISTS expense_date;
```

#### Шаг 3.2. Реализуй `ozon_cis_service.py` без ошибки границ дат и потери `missing_costs` (Copilot #12, #13, #14, #16)
В `backend/app/services/ozon_cis_service.py`:
1. При дедупликации выкупов СНГ (`raw_ozon_cis_buyouts`) против внутренних начислений (`raw_ozon_finance_ops`) **не ограничивай** запрос внутренних начислений нижней границей `date_from`. Ищи по точному списку `posting_number` из найденных выкупов СНГ:
```python
cis_postings = sorted({str(r["posting_number"]) for r in cis_rows if r.get("posting_number")})
already_accrued_postings: set[str] = set()
if cis_postings:
    found = ch.query(
        "SELECT DISTINCT JSONExtractString(payload, 'unit_number') AS posting_number"
        " FROM raw_ozon_finance_ops FINAL"
        " WHERE account_id IN {aids:Array(String)}"
        "   AND source = 'accrual_by_day'"
        "   AND JSONExtractString(payload, 'accrued_category') = 'POSTING'"
        "   AND JSONExtractString(payload, 'unit_number') IN {postings:Array(String)}",
        parameters={"aids": account_ids, "postings": cis_postings},
    ).result_rows
    already_accrued_postings = {str(row[0]) for row in found if row[0]}
```
2. Если для товара из `raw_ozon_cis_buyouts` (не попавшего в `already_accrued_postings`) себестоимость в `dim_offer_cost` / `dim_product_cost` не найдена или равна `0`, добавляй `offer_id` в возвращаемое множество `missing_cost_offers: set[str]`.

#### Шаг 3.3. Пересчитывай `margin_pct` в `PnlService` (Copilot #15)
В `backend/app/services/pnl_service.py` после применения корректировок СНГ и финансирования к строке `PnlRow` пересчитывай `margin_pct`:
```python
net_rev = row.revenue_rub - row.returns_cost_rub
row.margin_pct = round((row.gross_profit_rub / net_rev) * 100.0, 2) if net_rev > 0 else 0.0
```

#### Шаг 3.4. Внедри `DailyPnlService` и обнови фронтенд (`PnL.jsx`, `Dashboard.jsx`, `Taxes.jsx`)
1. В `backend/app/api/v1/pnl.py` при создании, изменении или удалении расхода (`/expenses`) добавь `cache: QueryCacheDependency` и вызывай `if cache is not None: cache.invalidate()`.
2. В `frontend/src/pages/PnL.jsx`:
   * В `useEffect` загрузки данных добавь `let cancelled = false; ... return () => { cancelled = true; };` (**Copilot #3**).
   * В коллбэке сохранения/удаления расхода вызывай перезагрузку как `/api/v1/pnl/expenses`, так и `/api/v1/pnl/daily` (**Copilot #23**).
   * Таблицу «Структура расходов» строй целиком из агрегатов выбранного диапазона дат `daily`, не смешивая в одной колонке месячные и дневные суммы (**Copilot #22**).
3. В `frontend/src/pages/Dashboard.jsx`:
   * Запрашивай `/api/v1/pnl/daily` через `safeCall`. Если пользователь имеет роль `viewer` или `analyst` (ответ `ok === false`), отображай стандартные карточки из `/api/v1/sales/daily` и `/api/v1/finance/daily` без показа ошибки (**Copilot #20**).
   * Проверяй поле `has_data` в ответе `/api/v1/pnl/daily`: если `has_data === false`, не рендери ложный `0 ₽` (**Copilot #19**).
   * Подпись налога формируй условно: `pnl.tax_enabled ? "после вычета налога" : "до вычета налога"` (**Copilot #21**).

---

### PR #4: Потоварная юнит-экономика (Article Economics) с алгоритмом $O(N + S)$

**Ветка:** `git checkout -b feat/article-economics main`

Этот PR — сердце аналитики PR #72. Ниже приведён **полный, оптимизированный за $O(N + S)$ эталонный код** вычислительного ядра и сервиса, который полностью устраняет квадратичную сложность $O(N \times S)$ (**Copilot #18**) и все ошибки мультиаккаунтности (**Copilot #8, #9, #10, #11**).

#### Шаг 4.1. Создай `common/article_economics.py` (Алгоритм $O(N + S)$)

Создай файл `common/article_economics.py` со следующим содержимым:

```python
"""High-performance O(N + S) article-level unit economics engine.

Key architectural invariants:
1. Composite key ``ArticleKey = tuple[str, str]`` -> ``(account_id, sku)`` prevents
   cross-account SKU collisions (Copilot #8).
2. Accrual line items return their exact monetary delta in O(1) without re-scanning
   the SKU dictionary on every operation, reducing complexity from O(N * S) to O(N + S)
   (Copilot #18).
3. Taxes are allocated strictly within the account(s) they belong to (Copilot #10),
   preserving the upstream tax status ('realization' | 'estimated' | 'disabled')
   (Copilot #11).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# (account_id, sku_or_product_id)
type ArticleKey = tuple[str, str]


@dataclass
class ArticleAccumulator:
    """Mutable O(1) per-article accumulator scoped to a single (account_id, sku)."""

    account_id: str
    marketplace: str
    sku: str
    offer_id: str = ""
    title: str = ""
    image_url: str | None = None
    cost_price_rub: float | None = None

    sales_qty: int = 0
    returns_qty: int = 0
    sales_rub: float = 0.0
    returns_rub: float = 0.0
    commission_rub: float = 0.0
    acquiring_rub: float = 0.0
    logistics_rub: float = 0.0
    reverse_logistics_rub: float = 0.0
    storage_rub: float = 0.0
    other_mp_fees_rub: float = 0.0
    direct_ad_cost_rub: float = 0.0

    @property
    def net_qty(self) -> int:
        return self.sales_qty - self.returns_qty

    @property
    def net_revenue_rub(self) -> float:
        return self.sales_rub - abs(self.returns_rub)

    @property
    def total_mp_fees_rub(self) -> float:
        """Signed sum of marketplace deductions (negative when charges exceed compensations)."""
        return (
            self.commission_rub
            + self.acquiring_rub
            + self.logistics_rub
            + self.reverse_logistics_rub
            + self.storage_rub
            + self.other_mp_fees_rub
        )

    @property
    def net_accrued_before_unallocated_rub(self) -> float:
        """O(1) net accrued directly attributed to this SKU."""
        return self.sales_rub - abs(self.returns_rub) + self.total_mp_fees_rub


@dataclass(frozen=True)
class ArticleEconomicsRow:
    """Finalized unit economics row ready for API serialization or aggregation."""

    marketplace: str
    account_id: str
    sku: str
    offer_id: str
    title: str
    image_url: str | None
    sales_qty: int
    returns_qty: int
    net_qty: int
    sales_rub: float
    returns_rub: float
    net_revenue_rub: float
    commission_rub: float
    acquiring_rub: float
    logistics_rub: float
    reverse_logistics_rub: float
    storage_rub: float
    other_mp_fees_rub: float
    allocated_mp_overhead_rub: float
    net_accrued_rub: float
    unit_cost_rub: float | None
    cogs_rub: float
    missing_cost: bool
    direct_ad_cost_rub: float
    allocated_ad_cost_rub: float
    total_ad_cost_rub: float
    gross_profit_rub: float
    allocated_indirect_expenses_rub: float
    operating_profit_rub: float
    allocated_tax_rub: float
    net_profit_rub: float
    margin_pct: float
    markup_pct: float | None
    abc_revenue_class: str = "C"
    abc_profit_class: str = "C"


@dataclass(frozen=True)
class ArticleEconomicsReport:
    """Complete report with rows, totals, and data-quality flags."""

    items: list[ArticleEconomicsRow]
    missing_cost_offers: list[str]
    tax_status: str
    tax_enabled: bool
    total_revenue_rub: float
    total_net_accrued_rub: float
    total_cogs_rub: float
    total_ad_cost_rub: float
    total_indirect_expenses_rub: float
    total_tax_rub: float
    total_net_profit_rub: float


@dataclass
class ArticleEconomicsEngine:
    """O(N + S) streaming accumulator for article-level unit economics."""

    _items: dict[ArticleKey, ArticleAccumulator] = field(default_factory=dict)
    _offer_to_sku: dict[tuple[str, str], str] = field(default_factory=dict)
    _unallocated_mp_by_account: defaultdict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    _unallocated_ad_by_account: defaultdict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    _running_attributed_net: float = 0.0

    def register_card(
        self,
        *,
        account_id: str,
        marketplace: str,
        sku: str,
        offer_id: str = "",
        title: str = "",
        image_url: str | None = None,
        cost_price_rub: float | None = None,
    ) -> ArticleAccumulator:
        """Register or enrich a product card under composite key (account_id, sku)."""
        norm_sku = str(sku).strip()
        norm_offer = str(offer_id).strip()
        key: ArticleKey = (account_id, norm_sku)
        acc = self._items.get(key)
        if acc is None:
            acc = ArticleAccumulator(
                account_id=account_id,
                marketplace=marketplace,
                sku=norm_sku,
                offer_id=norm_offer,
                title=title,
                image_url=image_url,
                cost_price_rub=cost_price_rub,
            )
            self._items[key] = acc
        else:
            if norm_offer and not acc.offer_id:
                acc.offer_id = norm_offer
            if title and not acc.title:
                acc.title = title
            if image_url and not acc.image_url:
                acc.image_url = image_url
            if cost_price_rub is not None and cost_price_rub > 0:
                acc.cost_price_rub = cost_price_rub

        if norm_offer:
            self._offer_to_sku[(account_id, norm_offer)] = norm_sku
        return acc

    def resolve_sku(self, account_id: str, sku_or_offer: str) -> str:
        """Resolve an offer_id to its canonical SKU within the same account."""
        candidate = str(sku_or_offer).strip()
        if (account_id, candidate) in self._items:
            return candidate
        return self._offer_to_sku.get((account_id, candidate), candidate)

    def add_line_movement(
        self,
        *,
        account_id: str,
        marketplace: str,
        sku: str,
        offer_id: str = "",
        title: str = "",
        sales_qty: int = 0,
        returns_qty: int = 0,
        sales_rub: float = 0.0,
        returns_rub: float = 0.0,
        commission_rub: float = 0.0,
        acquiring_rub: float = 0.0,
        logistics_rub: float = 0.0,
        reverse_logistics_rub: float = 0.0,
        storage_rub: float = 0.0,
        other_mp_fees_rub: float = 0.0,
    ) -> float:
        """Apply a single item movement in O(1) time and return its exact net delta."""
        resolved_sku = self.resolve_sku(account_id, sku or offer_id)
        acc = self.register_card(
            account_id=account_id,
            marketplace=marketplace,
            sku=resolved_sku,
            offer_id=offer_id,
            title=title,
        )
        acc.sales_qty += int(sales_qty)
        acc.returns_qty += int(returns_qty)
        acc.sales_rub += float(sales_rub)
        acc.returns_rub += abs(float(returns_rub))
        acc.commission_rub += float(commission_rub)
        acc.acquiring_rub += float(acquiring_rub)
        acc.logistics_rub += float(logistics_rub)
        acc.reverse_logistics_rub += float(reverse_logistics_rub)
        acc.storage_rub += float(storage_rub)
        acc.other_mp_fees_rub += float(other_mp_fees_rub)

        delta = (
            float(sales_rub)
            - abs(float(returns_rub))
            + float(commission_rub)
            + float(acquiring_rub)
            + float(logistics_rub)
            + float(reverse_logistics_rub)
            + float(storage_rub)
            + float(other_mp_fees_rub)
        )
        self._running_attributed_net += delta
        return delta

    def process_accrual_operation(
        self,
        *,
        account_id: str,
        marketplace: str,
        total_operation_amount: float,
        line_items: Iterable[Mapping[str, Any]],
    ) -> float:
        """Process one accrual operation in O(k) where k is items in the posting (not O(S)).

        Any remainder between ``total_operation_amount`` and the sum of line-item deltas
        is recorded into ``_unallocated_mp_by_account[account_id]`` in O(1).
        """
        attributed_delta = 0.0
        for item in line_items:
            attributed_delta += self.add_line_movement(
                account_id=account_id,
                marketplace=marketplace,
                sku=str(item.get("sku") or ""),
                offer_id=str(item.get("offer_id") or ""),
                title=str(item.get("title") or ""),
                sales_qty=int(item.get("sales_qty") or 0),
                returns_qty=int(item.get("returns_qty") or 0),
                sales_rub=float(item.get("sales_rub") or 0.0),
                returns_rub=float(item.get("returns_rub") or 0.0),
                commission_rub=float(item.get("commission_rub") or 0.0),
                acquiring_rub=float(item.get("acquiring_rub") or 0.0),
                logistics_rub=float(item.get("logistics_rub") or 0.0),
                reverse_logistics_rub=float(item.get("reverse_logistics_rub") or 0.0),
                storage_rub=float(item.get("storage_rub") or 0.0),
                other_mp_fees_rub=float(item.get("other_mp_fees_rub") or 0.0),
            )
        remainder = float(total_operation_amount) - attributed_delta
        if abs(remainder) >= 0.005:
            self._unallocated_mp_by_account[account_id] += remainder
        return attributed_delta

    def add_unallocated_mp_fee(self, account_id: str, amount_rub: float) -> None:
        """Record an account-level marketplace fee/compensation not tied to a single SKU."""
        self._unallocated_mp_by_account[account_id] += float(amount_rub)

    def add_sku_ad_cost(
        self,
        *,
        account_id: str,
        marketplace: str,
        sku: str,
        cost_rub: float,
        offer_id: str = "",
    ) -> None:
        """Attribute direct SKU advertising spend in O(1)."""
        resolved_sku = self.resolve_sku(account_id, sku or offer_id)
        acc = self.register_card(
            account_id=account_id,
            marketplace=marketplace,
            sku=resolved_sku,
            offer_id=offer_id,
        )
        acc.direct_ad_cost_rub += abs(float(cost_rub))

    def add_unallocated_ad_cost(self, account_id: str, cost_rub: float) -> None:
        """Record campaign ad spend that could not be attributed to a specific SKU."""
        self._unallocated_ad_by_account[account_id] += abs(float(cost_rub))

    def finalize(
        self,
        *,
        indirect_expenses_rub: float = 0.0,
        tax_by_account: Mapping[str, float] | None = None,
        tax_status: str = "disabled",
        tax_enabled: bool = False,
        merge_accounts: bool = False,
    ) -> ArticleEconomicsReport:
        """Single O(S log S) finalization pass to allocate overheads, taxes, and ABC classes."""
        taxes = dict(tax_by_account or {})
        active_accumulators = [
            acc
            for acc in self._items.values()
            if (
                acc.sales_qty > 0
                or acc.returns_qty > 0
                or abs(acc.sales_rub) > 0.005
                or abs(acc.total_mp_fees_rub) > 0.005
                or acc.direct_ad_cost_rub > 0.005
            )
        ]

        # 1. Compute revenue weights per account and globally in O(S)
        account_revenue: defaultdict[str, float] = defaultdict(float)
        account_counts: defaultdict[str, int] = defaultdict(int)
        for acc in active_accumulators:
            rev = max(0.0, acc.net_revenue_rub)
            account_revenue[acc.account_id] += rev
            account_counts[acc.account_id] += 1

        total_org_revenue = sum(account_revenue.values())
        total_active_count = len(active_accumulators)

        def _account_share(acc: ArticleAccumulator) -> float:
            acct_rev = account_revenue[acc.account_id]
            if acct_rev > 0:
                return max(0.0, acc.net_revenue_rub) / acct_rev
            cnt = account_counts[acc.account_id]
            return (1.0 / cnt) if cnt > 0 else 0.0

        def _org_share(acc: ArticleAccumulator) -> float:
            if total_org_revenue > 0:
                return max(0.0, acc.net_revenue_rub) / total_org_revenue
            return (1.0 / total_active_count) if total_active_count > 0 else 0.0

        # 2. Build finalized rows per (account_id, sku)
        missing_cost_offers: set[str] = set()
        raw_rows: list[ArticleEconomicsRow] = []

        for acc in active_accumulators:
            acct_w = _account_share(acc)
            org_w = _org_share(acc)

            alloc_mp_overhead = self._unallocated_mp_by_account.get(acc.account_id, 0.0) * acct_w
            net_accrued = acc.net_accrued_before_unallocated_rub + alloc_mp_overhead

            alloc_ad = self._unallocated_ad_by_account.get(acc.account_id, 0.0) * acct_w
            total_ad = acc.direct_ad_cost_rub + alloc_ad

            has_activity = acc.sales_qty > 0 or acc.returns_qty > 0
            cost_missing = has_activity and (acc.cost_price_rub is None or acc.cost_price_rub <= 0)
            if cost_missing:
                missing_cost_offers.add(acc.offer_id or acc.sku)

            unit_cost = (
                acc.cost_price_rub if (acc.cost_price_rub and acc.cost_price_rub > 0) else None
            )
            cogs = (unit_cost * acc.net_qty) if unit_cost is not None else 0.0

            gross_profit = net_accrued - cogs
            alloc_indirect = float(indirect_expenses_rub) * org_w
            operating_profit = gross_profit - total_ad - alloc_indirect

            # Strictly scope tax to its target account_id (Fixes Copilot #10)
            acct_tax_Pool = abs(float(taxes.get(acc.account_id, 0.0)))
            alloc_tax = acct_tax_Pool * acct_w
            net_profit = operating_profit - alloc_tax

            net_rev = acc.net_revenue_rub
            margin_pct = round((net_profit / net_rev) * 100.0, 2) if net_rev > 0 else 0.0
            markup_pct = round((net_profit / cogs) * 100.0, 2) if cogs > 0 else None

            raw_rows.append(
                ArticleEconomicsRow(
                    marketplace=acc.marketplace,
                    account_id=acc.account_id,
                    sku=acc.sku,
                    offer_id=acc.offer_id or acc.sku,
                    title=acc.title,
                    image_url=acc.image_url,
                    sales_qty=acc.sales_qty,
                    returns_qty=acc.returns_qty,
                    net_qty=acc.net_qty,
                    sales_rub=round(acc.sales_rub, 2),
                    returns_rub=round(abs(acc.returns_rub), 2),
                    net_revenue_rub=round(net_rev, 2),
                    commission_rub=round(acc.commission_rub, 2),
                    acquiring_rub=round(acc.acquiring_rub, 2),
                    logistics_rub=round(acc.logistics_rub, 2),
                    reverse_logistics_rub=round(acc.reverse_logistics_rub, 2),
                    storage_rub=round(acc.storage_rub, 2),
                    other_mp_fees_rub=round(acc.other_mp_fees_rub, 2),
                    allocated_mp_overhead_rub=round(alloc_mp_overhead, 2),
                    net_accrued_rub=round(net_accrued, 2),
                    unit_cost_rub=round(unit_cost, 2) if unit_cost is not None else None,
                    cogs_rub=round(cogs, 2),
                    missing_cost=cost_missing,
                    direct_ad_cost_rub=round(acc.direct_ad_cost_rub, 2),
                    allocated_ad_cost_rub=round(alloc_ad, 2),
                    total_ad_cost_rub=round(total_ad, 2),
                    gross_profit_rub=round(gross_profit, 2),
                    allocated_indirect_expenses_rub=round(alloc_indirect, 2),
                    operating_profit_rub=round(operating_profit, 2),
                    allocated_tax_rub=round(alloc_tax, 2),
                    net_profit_rub=round(net_profit, 2),
                    margin_pct=margin_pct,
                    markup_pct=markup_pct,
                )
            )

        rows = _merge_across_accounts(raw_rows) if merge_accounts else raw_rows
        classified = _assign_abc_classes(rows)

        return ArticleEconomicsReport(
            items=classified,
            missing_cost_offers=sorted(missing_cost_offers),
            tax_status=tax_status,
            tax_enabled=tax_enabled,
            total_revenue_rub=round(sum(r.net_revenue_rub for r in classified), 2),
            total_net_accrued_rub=round(sum(r.net_accrued_rub for r in classified), 2),
            total_cogs_rub=round(sum(r.cogs_rub for r in classified), 2),
            total_ad_cost_rub=round(sum(r.total_ad_cost_rub for r in classified), 2),
            total_indirect_expenses_rub=round(
                sum(r.allocated_indirect_expenses_rub for r in classified), 2
            ),
            total_tax_rub=round(sum(r.allocated_tax_rub for r in classified), 2),
            total_net_profit_rub=round(sum(r.net_profit_rub for r in classified), 2),
        )


def _merge_across_accounts(rows: list[ArticleEconomicsRow]) -> list[ArticleEconomicsRow]:
    """Optional post-calculation aggregation by offer_id AFTER per-account COGS & tax."""
    grouped: dict[tuple[str, str], list[ArticleEconomicsRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.marketplace, row.offer_id or row.sku)].append(row)

    merged: list[ArticleEconomicsRow] = []
    for (marketplace, offer_key), group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        first = group[0]
        sales_qty = sum(r.sales_qty for r in group)
        returns_qty = sum(r.returns_qty for r in group)
        net_qty = sales_qty - returns_qty
        net_rev = sum(r.net_revenue_rub for r in group)
        cogs = sum(r.cogs_rub for r in group)
        net_profit = sum(r.net_profit_rub for r in group)
        merged.append(
            ArticleEconomicsRow(
                marketplace=marketplace,
                account_id="all",
                sku=first.sku,
                offer_id=offer_key,
                title=next((r.title for r in group if r.title), ""),
                image_url=next((r.image_url for r in group if r.image_url), None),
                sales_qty=sales_qty,
                returns_qty=returns_qty,
                net_qty=net_qty,
                sales_rub=round(sum(r.sales_rub for r in group), 2),
                returns_rub=round(sum(r.returns_rub for r in group), 2),
                net_revenue_rub=round(net_rev, 2),
                commission_rub=round(sum(r.commission_rub for r in group), 2),
                acquiring_rub=round(sum(r.acquiring_rub for r in group), 2),
                logistics_rub=round(sum(r.logistics_rub for r in group), 2),
                reverse_logistics_rub=round(sum(r.reverse_logistics_rub for r in group), 2),
                storage_rub=round(sum(r.storage_rub for r in group), 2),
                other_mp_fees_rub=round(sum(r.other_mp_fees_rub for r in group), 2),
                allocated_mp_overhead_rub=round(sum(r.allocated_mp_overhead_rub for r in group), 2),
                net_accrued_rub=round(sum(r.net_accrued_rub for r in group), 2),
                unit_cost_rub=round(cogs / net_qty, 2)
                if net_qty > 0 and cogs > 0
                else first.unit_cost_rub,
                cogs_rub=round(cogs, 2),
                missing_cost=any(r.missing_cost for r in group),
                direct_ad_cost_rub=round(sum(r.direct_ad_cost_rub for r in group), 2),
                allocated_ad_cost_rub=round(sum(r.allocated_ad_cost_rub for r in group), 2),
                total_ad_cost_rub=round(sum(r.total_ad_cost_rub for r in group), 2),
                gross_profit_rub=round(sum(r.gross_profit_rub for r in group), 2),
                allocated_indirect_expenses_rub=round(
                    sum(r.allocated_indirect_expenses_rub for r in group), 2
                ),
                operating_profit_rub=round(sum(r.operating_profit_rub for r in group), 2),
                allocated_tax_rub=round(sum(r.allocated_tax_rub for r in group), 2),
                net_profit_rub=round(net_profit, 2),
                margin_pct=round((net_profit / net_rev) * 100.0, 2) if net_rev > 0 else 0.0,
                markup_pct=round((net_profit / cogs) * 100.0, 2) if cogs > 0 else None,
            )
        )
    return merged


def _assign_abc_classes(rows: list[ArticleEconomicsRow]) -> list[ArticleEconomicsRow]:
    """Assign ABC classes by net revenue and by net profit in O(S log S)."""
    if not rows:
        return []

    def _classify(metric_fn: Any) -> dict[tuple[str, str, str], str]:
        ordered = sorted(
            rows,
            key=lambda r: (max(0.0, float(metric_fn(r))), r.net_revenue_rub),
            reverse=True,
        )
        total = sum(max(0.0, float(metric_fn(r))) for r in ordered)
        classes: dict[tuple[str, str, str], str] = {}
        cumulative = 0.0
        for r in ordered:
            key = (r.marketplace, r.account_id, r.sku)
            val = max(0.0, float(metric_fn(r)))
            if total <= 0 or val <= 0:
                classes[key] = "C"
                continue
            cumulative += val / total
            if cumulative <= 0.80:
                classes[key] = "A"
            elif cumulative <= 0.95:
                classes[key] = "B"
            else:
                classes[key] = "C"
        return classes

    rev_abc = _classify(lambda r: r.net_revenue_rub)
    prof_abc = _classify(lambda r: r.net_profit_rub)

    result = [
        ArticleEconomicsRow(
            **{
                **r.__dict__,
                "abc_revenue_class": rev_abc[(r.marketplace, r.account_id, r.sku)],
                "abc_profit_class": prof_abc[(r.marketplace, r.account_id, r.sku)],
            }
        )
        for r in rows
    ]
    return sorted(result, key=lambda r: (r.net_revenue_rub, r.net_profit_rub), reverse=True)
```

#### Шаг 4.2. Добавь обязательный unit-тест на скорость $O(N + S)$ и мультиаккаунтность
Создай тест `tests/unit/test_article_economics_engine.py`:
```python
from __future__ import annotations

import time
import pytest
from common.article_economics import ArticleEconomicsEngine


def test_multi_account_sku_isolation_and_scoped_tax() -> None:
    """Fixes Copilot #8 and #10: two accounts with the same SKU keep distinct COGS and tax."""
    engine = ArticleEconomicsEngine()
    engine.register_card(
        account_id="acc-taxed",
        marketplace="ozon",
        sku="100500",
        offer_id="ART-1",
        cost_price_rub=100.0,
    )
    engine.register_card(
        account_id="acc-untaxed",
        marketplace="ozon",
        sku="100500",
        offer_id="ART-1",
        cost_price_rub=300.0,
    )

    engine.process_accrual_operation(
        account_id="acc-taxed",
        marketplace="ozon",
        total_operation_amount=900.0,
        line_items=[
            {"sku": "100500", "sales_qty": 1, "sales_rub": 1000.0, "commission_rub": -100.0}
        ],
    )
    engine.process_accrual_operation(
        account_id="acc-untaxed",
        marketplace="ozon",
        total_operation_amount=900.0,
        line_items=[
            {"sku": "100500", "sales_qty": 1, "sales_rub": 1000.0, "commission_rub": -100.0}
        ],
    )

    report = engine.finalize(
        tax_by_account={"acc-taxed": 60.0},
        tax_status="estimated",
        tax_enabled=True,
    )
    by_acc = {r.account_id: r for r in report.items}

    assert by_acc["acc-taxed"].cogs_rub == 100.0
    assert by_acc["acc-untaxed"].cogs_rub == 300.0
    assert by_acc["acc-taxed"].allocated_tax_rub == 60.0
    assert by_acc["acc-untaxed"].allocated_tax_rub == 0.0
    assert report.total_cogs_rub == 400.0
    assert report.tax_status == "estimated"


def test_linear_o_n_plus_s_performance_under_50k_operations() -> None:
    """Fixes Copilot #18: 50,000 operations across 500 SKUs must complete in < 0.5s."""
    engine = ArticleEconomicsEngine()
    for i in range(500):
        engine.register_card(
            account_id="default",
            marketplace="ozon",
            sku=str(1000 + i),
            offer_id=f"OFFER-{i}",
            cost_price_rub=50.0,
        )

    started = time.perf_counter()
    for n in range(50_000):
        sku = str(1000 + (n % 500))
        engine.process_accrual_operation(
            account_id="default",
            marketplace="ozon",
            total_operation_amount=175.0,
            line_items=[{"sku": sku, "sales_qty": 1, "sales_rub": 200.0, "commission_rub": -20.0}],
        )
    report = engine.finalize()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"Engine took {elapsed:.2f}s (expected O(N + S) < 0.5s)"
    assert len(report.items) == 500
    assert report.total_net_accrued_rub == pytest.approx(50_000 * 175.0)
```

---

### PR #5: Воронка конверсий Ozon (`0050`) и ручной импорт отчётов

**Ветка:** `git checkout -b feat/ozon-funnel-import main`

#### Шаг 5.1. Создай миграцию `0050_ozon_funnel_import.sql` (+ rollback)
* **`warehouse/migrations/0050_ozon_funnel_import.sql`**:
```sql
CREATE TABLE IF NOT EXISTS raw_ozon_funnel_import
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  sku UInt64,
  offer_id String,
  title String DEFAULT '',
  scheme LowCardinality(String) DEFAULT 'ALL',
  views UInt64 DEFAULT 0,
  views_search UInt64 DEFAULT 0,
  views_card UInt64 DEFAULT 0,
  adds_to_cart UInt64 DEFAULT 0,
  orders UInt64 DEFAULT 0,
  orders_sum_rub Float64 DEFAULT 0,
  delivered_qty UInt64 DEFAULT 0,
  returns_qty UInt64 DEFAULT 0,
  cancelled_qty UInt64 DEFAULT 0,
  payload String DEFAULT ''
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, sku, scheme);
```
* **`warehouse/migrations/rollbacks/0050_ozon_funnel_import.sql`**:
```sql
DROP TABLE IF EXISTS raw_ozon_funnel_import;
```

#### Шаг 5.2. Закрой утечку себестоимости и исправь пагинацию в `backend/app/api/v1/funnel.py` (Copilot #1, #6)
1. В эндпоинте `/api/v1/funnel/ozon/related` (`backend/app/api/v1/funnel.py`):
   * Проверяй роль вызывающего пользователя через `auth.allows(OrgMemberRole.manager)`.
   * Если `not auth.allows(OrgMemberRole.manager)`, **не выполняй** запрос к `dim_offer_cost` / `dim_product_cost` и возвращай `"cost_price_rub": None`.
2. В SQL-запросе пагинации `/api/v1/funnel/ozon` зафиксируй однозначный порядок сортировки с `account_id`:
   ```sql
   ORDER BY day DESC, account_id ASC, sku ASC, scheme ASC
   LIMIT {limit:UInt32} OFFSET {offset:UInt32}
   ```

---

### PR #6: Документация, E2E-тесты и обновление демо-скриншотов

**Ветка:** `git checkout -b chore/pr72-docs-and-e2e main`

1. Обнови `docs/data_catalog.md`: добавь описание таблиц `raw_ozon_realization_reports`, `raw_ozon_sku_ad_reports`, `raw_ozon_cis_buyouts`, `raw_ozon_campaigns`, `raw_ozon_funnel_import`, `sys_ozon_report_jobs` и расчёта потоварной юнит-экономики.
2. В `frontend/scripts/readme-screenshots.mjs` добавь демо-роуты в объект `routes`:
   * `"/api/v1/pnl/daily"`
   * `"/api/v1/economics"`
   * `"/api/v1/funnel/ozon"`
3. В `frontend/e2e/smoke.spec.js` добавь проверку того, что под ролью `viewer` (`Ann Viewer`) дашборд (`#/dashboard`) открывается без ошибок, несмотря на то что `/api/v1/pnl/daily` отвечает `403`.
4. Удали временный аналитический файл `docs/pr-72-comprehensive-analysis.md`, если он присутствовал в рабочей ветке, и зафиксируй релизные заметки в `CHANGELOG.md`.

---

## 4. Финальный чек-лист самопроверки агента (Definition of Done)

После завершения каждого PR агент обязан выполнить следующий блок команд и убедиться, что код возврата равен `0` на каждом шаге:

```bash
# 1. Проверка синтаксиса, форматирования и строгой типизации Python 3.14
ruff check .
ruff format --check .
mypy backend workers collectors automation warehouse scripts common

# 2. Проверка манифеста миграций (наличие всех rollbacks 0005..0050)
python warehouse/apply_migrations.py verify

# 3. Проверка актуальности waivers безопасности
python scripts/check_vuln_waivers.py

# 4. Запуск полного набора тестов (Unit + Worker Suite + ClickHouse/Redis Integration)
pytest -q

# 5. Сборка фронтенда, аудит npm и тесты браузерного расширения
cd frontend && npm ci && npm audit --audit-level=high && npm run build
node --test "../browser_extension/tests/*.test.mjs"

# 6. Запуск E2E smoke-тестов Playwright
npx playwright test
```