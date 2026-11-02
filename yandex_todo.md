> Состояние реализации и открытые ограничения: [docs/yandex_market_status.md](docs/yandex_market_status.md).

# План реализации полной поддержки Яндекс.Маркета (`ym`) в BormoStats для GPT-6 Luna

## 1. Контекст и текущее состояние проекта

* В репозитории уже есть справочная документация по API Яндекс.Маркета в файле `docs/ym_partner_api.md`, однако в коде проекта реализована поддержка только двух маркетплейсов: `wb` и `ozon`.


* Ограничение `wb | ozon` жёстко задано в регулярных выражениях FastAPI-роутеров (`r"^(wb|ozon)$"`), Pydantic-моделях (`Literal["wb", "ozon"]`), коллекторах (`collectors/`), Celery-задачах (`workers/app/tasks/`), SQL-трансформациях (`workers/app/sql/`) и React-интерфейсе (`frontend/src/`).


* Цель задачи — внедрить код маркетплейса `ym` (Яндекс.Маркет) во все контуры системы наравне с `wb` и `ozon`: сбор сырых данных, история карточек (`hist_*`), трансформации в `stg_*`, расчёт витрин (`mrt_*`), финансы и P&L, прайсинг и репрайсер, биддер (Буст продаж), отзывы с ИИ/шаблонами, пуш остатков, плагин/расширение и UI.



---

## 2. Архитектура интеграции с Yandex Market Partner API

* **Базовый URL и авторизация**: Все запросы выполняются к `[https://api.partner.market.yandex.ru](https://api.partner.market.yandex.ru)` с заголовком `Api-Key: <YM_API_KEY>`.
* **Иерархия идентификаторов Маркета**:
* `businessId` (ID кабинета/бизнеса) — используется для каталога, карточек, базовых цен, отзывов (`goods-feedback`) и ставок буста продаж (`bids`).
* `campaignId` (ID магазина внутри бизнеса: FBY, FBS, Express, DBS) — используется для заказов, остатков на складах, цен магазина и финансовых отчётов.


* **Маппинг сущностей Маркета на схему данных BormoStats**:
* `marketplace` = `'ym'` во всех таблицах ClickHouse и API.


* `account_id` = строковое представление `campaignId` (либо `"default"` при одном магазине с маппингом на `YM_CAMPAIGN_ID` и `YM_BUSINESS_ID`).


* `offer_id` (артикул продавца) = `offerId` (String, до 128 символов).


* `product_id` = `marketSku` (`UInt64` в `raw_*`/`stg_*`/`mrt_*` и `String` в `dim_product`, `mrt_price_current`, `fct_review`); если у товара ещё не назначен `marketSku`, в качестве фоллбэка использовать `cityHash64(offerId)` для `UInt64`-таблиц.





---

## 3. Конфигурация и переменные окружения

* **`backend/app/core/config.py` и `.env*.example**`:
* Добавить поля в класс `Settings` (`backend/app/core/config.py`): `ym_api_key: str = Field(default="", alias="YM_API_KEY")`, `ym_business_id: str = Field(default="", alias="YM_BUSINESS_ID")`, `ym_campaign_id: str = Field(default="", alias="YM_CAMPAIGN_ID")`.


* Добавить соответствующие переменные в `.env.example`, `.env.dev.example`, `.env.stage.example`, `.env.prod.example` и скрипт валидации `common/env_validation.py` + `scripts/check_tokens.py`.




* **`collectors/common/redaction.py`**:
* Убедиться, что заголовок `Api-Key` маскируется в логах HTTP-клиента наравне с токенами WB и Ozon.





---

## 4. Слой коллекторов (`collectors/ym/`)

Создать пакет `collectors/ym/` по аналогии с `collectors/ozon/` и `collectors/wb/`:

* **`collectors/ym/__init__.py` и `collectors/ym/errors.py**`:
* Описать классы исключений `YmApiError`, `YmRateLimitError`, `YmAuthError` по образцу `collectors/ozon/errors.py`.




* **`collectors/ym/endpoints.py`**:
* Определить константы эндпоинтов:
* Кампании и настройки: `GET /v2/campaigns`, `POST /v2/businesses/{businessId}/settings`.
* Каталог и карточки: `POST /v2/businesses/{businessId}/offer-mappings`, `POST /v2/businesses/{businessId}/offer-cards`, `POST /v2/campaigns/{campaignId}/offers`.
* Заказы и статистика заказов: `POST /v1/businesses/{businessId}/orders`, `POST /v2/campaigns/{campaignId}/stats/orders`.
* Остатки и склады: `POST /v2/campaigns/{campaignId}/offers/stocks`, `PUT /v2/campaigns/{campaignId}/offers/stocks`, `GET /v2/warehouses`, `POST /v1/businesses/{businessId}/warehouses`.
* Цены и тарифы: `POST /v2/campaigns/{campaignId}/offer-prices`, `POST /v2/businesses/{businessId}/offer-prices/updates`, `POST /v2/campaigns/{campaignId}/offer-prices/updates`, `POST /v2/tariffs/calculate`.
* Асинхронные отчёты (Финансы, Воронка, Буст): `POST /v2/reports/united-netting/generate`, `POST /v2/reports/shows-sales/generate`, `POST /v2/reports/shows-boost/generate`, `GET /v2/reports/info/{reportId}`.
* Ставки Буста продаж (Bidder): `POST /v2/businesses/{businessId}/bids/info`, `POST /v2/businesses/{businessId}/bids/recommendations`, `PUT /v2/businesses/{businessId}/bids`.
* Отзывы: `POST /v2/businesses/{businessId}/goods-feedback`, `POST /v2/businesses/{businessId}/goods-feedback/comments`, `POST /v2/businesses/{businessId}/goods-feedback/comments/update`.




* **`collectors/ym/client.py`**:
* Реализовать `YmClient` поверх `collectors/common/http_client.py` и `collectors/common/retry.py` с заголовком `{"Api-Key": self.api_key}`.


* Реализовать курсорную пагинацию через `page_token` / `nextPageToken` (передаётся в query-параметре `page_token` или теле запроса в зависимости от метода).
* Реализовать хелпер генерации и скачивания асинхронных отчётов (`generate_and_fetch_report`): отправка `POST /v2/reports/{type}/generate` с `format="CSV"` или `"JSON"`, поллинг `GET /v2/reports/info/{reportId}` до статуса `DONE`, скачивание и распаковка ZIP/CSV-архива в память.


* **`collectors/ym/parsers.py`**:
* Реализовать чистые функции парсинга ответов API в строки для вставки в ClickHouse (`parse_orders`, `parse_stats_orders`, `parse_stocks`, `parse_offer_mappings`, `parse_prices`, `parse_united_netting`, `parse_shows_sales`, `parse_shows_boost`, `parse_feedbacks`) по аналогии с `collectors/ozon/parsers.py` и `collectors/wb/parsers.py`.





---

## 5. Действия на маркетплейсе и отзывы (`collectors/marketplace_actions.py`, `collectors/reviews.py`)

* **`collectors/marketplace_actions.py`**:
* Добавить класс `YmActionsClient`:
* `set_prices(prices: list[tuple[str, float]])`: вызывает `POST /v2/campaigns/{campaignId}/offer-prices/updates` (или `/v2/businesses/{businessId}/offer-prices/updates`) с массивом `offers: [{"offerId": offer_id, "price": {"value": price, "currencyId": "RUR"}}]`.


* `set_stocks(warehouse_id: int, stocks: list[tuple[str, int]])`: вызывает `PUT /v2/campaigns/{campaignId}/offers/stocks` с массивом `skus: [{"sku": offer_id, "warehouseId": warehouse_id, "items": [{"count": stock, "type": "FIT", "updatedAt": iso_now}]}]`.


* `set_bids(bids: list[tuple[str, float]])`: вызывает `PUT /v2/businesses/{businessId}/bids` для установки ставок Буста продаж (`bids: [{"sku": offer_id, "bid": int(bid * 100)}]`, где ставка в API передаётся в сотых долях процента либо в процентах согласно схеме `putBidsForBusiness`).






* **`collectors/reviews.py`**:
* Добавить сбор отзывов Яндекс.Маркета через `POST /v2/businesses/{businessId}/goods-feedback` с маппингом полей в `fct_review` (`review_id = str(feedbackId)`, `rating = statistics.rating`, `text = description.comment`, `pros = description.advantages`, `cons = description.disadvantages`, `is_answered = not needReaction`).


* В функцию `send_reply(...)` добавить ветку `marketplace == "ym"`, вызывающую `POST /v2/businesses/{businessId}/goods-feedback/comments/update` с телом `{"feedbackId": int(review_id), "comment": {"text": text}}`.


* Пробросить `ym_api_key` и `ym_business_id` в `send_reply` из `backend/app/services/review_service.py` и `workers/app/tasks/reviews.py`.





---

## 6. Схема БД ClickHouse (`warehouse/migrations/`)

Создать новую миграцию `warehouse/migrations/0039_yandex_market.sql` и соответствующий откат `warehouse/migrations/rollbacks/0039_yandex_market.sql` (не забыть проверить манифест через `python warehouse/apply_migrations.py verify`):

* **`raw_ym_orders`**: `run_id UUID`, `account_id String`, `order_id UInt64`, `offer_id String`, `product_id UInt64`, `status String`, `substatus String`, `created_at DateTime`, `updated_at DateTime`, `qty UInt32`, `buyer_price Float64`, `seller_price Float64`, `subsidy Float64`, `payload String`, `ingested_at DateTime` (`ReplacingMergeTree(ingested_at) ORDER BY (account_id, order_id, offer_id)`).


* **`raw_ym_stocks`**: `run_id UUID`, `account_id String`, `offer_id String`, `product_id UInt64`, `warehouse_id Int64`, `warehouse_name String`, `stock_fit Int64`, `stock_freeze Int64`, `snapshot_ts DateTime`, `payload String` (`ReplacingMergeTree(snapshot_ts) ORDER BY (account_id, offer_id, warehouse_id, snapshot_ts)`).


* **`raw_ym_prices`**: `run_id UUID`, `account_id String`, `offer_id String`, `product_id UInt64`, `list_price Float64`, `seller_price Float64`, `cofinance_price Nullable(Float64)`, `buyer_price Nullable(Float64)`, `commission_pct Float64`, `logistics_rub Float64`, `acquiring_rub Float64`, `snapshot_ts DateTime`, `payload String` (`ReplacingMergeTree(snapshot_ts) ORDER BY (account_id, offer_id)`).


* **`raw_ym_funnel`**: `run_id UUID`, `account_id String`, `day Date`, `offer_id String`, `product_id UInt64`, `shows UInt64`, `clicks UInt64`, `to_cart UInt64`, `orders UInt64`, `revenue Float64`, `ingested_at DateTime` (`ReplacingMergeTree(ingested_at) ORDER BY (account_id, day, product_id)`).


* **`raw_ym_ads`**: `run_id UUID`, `account_id String`, `day Date`, `campaign_id String`, `offer_id String`, `product_id UInt64`, `impressions UInt64`, `clicks UInt64`, `cost Float64`, `orders UInt64`, `revenue Float64`, `ingested_at DateTime` (`ReplacingMergeTree(ingested_at) ORDER BY (account_id, day, campaign_id, product_id)`).


* **`raw_ym_finance`**: `run_id UUID`, `account_id String`, `transaction_id String`, `event_date Date`, `order_id Nullable(UInt64)`, `offer_id String`, `transaction_type String`, `service_type String`, `amount Float64`, `payout Float64`, `payload String`, `ingested_at DateTime` (`ReplacingMergeTree(ingested_at) ORDER BY (account_id, event_date, transaction_id)`).


* **`raw_ym_campaigns`**: справочник кампаний/магазинов и их `business_id`, моделей работы (`FBY`, `FBS`, `DBS`, `EXPRESS`) для связки `account_id <-> campaign_id <-> business_id`.



---

## 7. SQL-трансформации и витрины (`workers/app/sql/` и `common/finance.py`)

* **Трансформации (`workers/app/sql/transforms/`)**:
* Создать `ym_orders_to_stg.sql` (заполнение `stg_orders` из `raw_ym_orders` с `marketplace = 'ym'`).


* Создать `ym_sales_to_stg.sql` (заполнение `stg_sales` по доставленным заказам `status = 'DELIVERED'` и возвратам `RETURNED`/`CANCELLED`, расчёт `revenue`, `qty`, `returns_qty`, `payout`).


* Создать `ym_stocks_to_stg.sql` (заполнение `stg_stocks` из `raw_ym_stocks`).


* Создать `ym_funnel_to_stg.sql` (заполнение `stg_funnel` из `raw_ym_funnel`).


* Создать `ym_ads_to_stg.sql` (заполнение `stg_ads` из `raw_ym_ads`).


* Создать `ym_finance_to_stg.sql` (заполнение `stg_finance` комиссиями и логистикой по товарам Маркета).


* Создать `sync_dim_product_ym.sql` и обновить `sync_dim_product_catalog.sql`, чтобы карточки Яндекс.Маркета (название, `offer_id`, фото `pictures[1]`) синхронизировались в `dim_product`.




* **Финансовая витрина (`common/finance.py` и `workers/app/sql/marts/`)**:
* Создать `workers/app/sql/marts/mrt_finance_daily_ym.sql` по образцу `mrt_finance_daily_ozon.sql` и `mrt_finance_daily_wb.sql`.


* В `common/finance.py` добавить правила классификации строк отчёта `united-netting` и `stats/orders` Яндекс.Маркета по категориям: `sales`, `returns`, `commission` (размещение товаров на витрине), `acquiring` (приём и перевод платежей), `logistics` (доставка покупателю, обработка на складе/СЦ), `reverse_logistics` (невыкупы и возвраты), `storage` (хранение на складе Маркета), `acceptance`, `penalties`, `other` (буст продаж, программа лояльности Плюс), `payouts`.




* **Витрина текущих цен (`workers/app/sql/marts/mrt_price_current.sql`)**:
* Добавить `UNION ALL` блок для `marketplace = 'ym'` на базе `raw_ym_prices`, карточек из `hist_refs`/`dim_product`, софинансирования скидок Маркетом (`mp_discount_pct` из разницы `seller_price` и `buyer_price`/`cofinance_price`), тарифов `commission_pct`, `logistics_rub`, `acquiring_rub`, себестоимости из `dim_offer_cost`/`dim_product_cost` и расчёта `margin_rub`, `margin_pct`, `breakeven_price`.




* **Запрос остатков (`backend/app/db/queries/stocks.sql`)**:
* В CTE `warehouses` добавить `UNION ALL` для `raw_ym_stocks` (`SELECT 'ym' AS marketplace, account_id, warehouse_id, argMax(warehouse_name, snapshot_ts) AS warehouse_name FROM raw_ym_stocks ...`) и ветку в `multiIf` (`s.warehouse_id IS NULL AND s.marketplace = 'ym', 'Склад Я.Маркет'`).





---

## 8. Фоновые задачи Celery (`workers/app/`)

* **`workers/app/tasks/ym_collect.py`**:
* Создать модуль задач сбора данных Маркета по аналогии с `ozon_collect.py` и `wb_collect.py`:


* `ym_orders_recent` и `ym_orders_backfill_days(days: int)`
* `ym_stocks_snapshot`
* `ym_prices_snapshot`
* `ym_funnel_recent` и `ym_funnel_backfill_days(days: int)`
* `ym_ads_recent`
* `ym_finance_recent` и `ym_finance_backfill_days(days: int)`
* `ym_balance_snapshot` (запись в `raw_marketplace_balance` с `marketplace = 'ym'`).




* Использовать водяные знаки (`sys_watermarks` с префиксами `ym_orders`, `ym_sales`, `ym_stocks`, `ym_funnel`, `ym_ads`, `ym_finance`), локи (`workers/app/utils/locking.py`) и запись статусов в `sys_task_runs`.




* **`workers/app/tasks/history.py` и `workers/app/utils/history_archive.py**`:
* Добавить задачу `ym_catalog_snapshot` для сохранения снимков карточек товаров Маркета в Git-подобное хранилище (`hist_objects`, `hist_commits`, `hist_refs`, `hist_changes` с `repo = 'product'`, `marketplace = 'ym'`).


* Зарегистрировать `raw_ym_*` таблицы в архиваторе статистических записей `history_archive.py`.




* **`workers/app/tasks/transforms.py` и `workers/app/tasks/marts.py**`:
* Включить вызовы `ym_*_to_stg.sql`, `sync_dim_product_ym.sql` и `mrt_finance_daily_ym.sql` в `transform_all_recent`, `transform_backfill_days`, `build_marts_recent`, `build_marts_backfill_days`.




* **`workers/app/tasks/repricer.py` и `workers/app/tasks/bidder.py**`:
* В `repricer.py` добавить обработку правил `marketplace == 'ym'` с отправкой цен через `YmActionsClient.set_prices` и записью аудита в `sys_marketplace_actions`.


* В `bidder.py` добавить синхронизацию кампаний и ставок Буста продаж для `marketplace == 'ym'` через `YmActionsClient.set_bids`.




* **`workers/app/beat_schedule.py` и `workers/app/celery_app.py**`:
* Зарегистрировать модуль `tasks.ym_collect` в `celery_app.py` и добавить периодические задачи `ym_*` в расписание `beat_schedule.py`.





---

## 9. Backend API, модели и сервисы (`backend/app/`)

* **Расширение валидации `marketplace` с `wb|ozon` до `wb|ozon|ym**`:
* Обновить `MarketplaceFilter = Literal["wb", "ozon", "ym"] | None` в `backend/app/models/api.py`.


* Обновить `MARKETPLACE_PATTERN = r"^(wb|ozon|ym)$"` в `backend/app/models/bidder.py`.


* Заменить все вхождения `r"^(wb|ozon)$"` на `r"^(wb|ozon|ym)$"` в файлах:
* `backend/app/api/v1/abc_xyz.py`


* `backend/app/api/v1/bidder.py`


* `backend/app/api/v1/costs.py`


* `backend/app/api/v1/history.py`


* `backend/app/api/v1/integrations.py`


* `backend/app/api/v1/pim.py`


* `backend/app/api/v1/plugin.py`


* `backend/app/api/v1/pricing.py`


* `backend/app/api/v1/repricer.py`


* `backend/app/api/v1/reviews.py`


* `backend/app/models/admin.py`


* `backend/app/models/exports.py`


* `backend/app/models/extension.py`


* `backend/app/models/organization.py`


* `backend/app/models/pim.py`


* `backend/app/models/pricing.py`






* **Админка и бэкфилл (`backend/app/models/admin.py`, `backend/app/services/admin_service.py`)**:
* В `BackfillMarketplace` добавить `YM = "ym"`.


* В `BACKFILL_MAX_DAYS` добавить лимиты для Маркета: `("ym", "orders"): 365`, `("ym", "sales"): 365`, `("ym", "funnel"): 365`, `("ym", "finance"): 730`.


* В `AdminService.queue_backfill` (`backend/app/services/admin_service.py`) добавить маппинг этих пар на задачи `tasks.ym_collect.*`.




* **Мониторинг свежести данных (`backend/app/services/freshness_service.py`)**:
* Обновить `COLLECTOR_TASK_PREFIXES = ("tasks.wb_collect.", "tasks.ozon_collect.", "tasks.ym_collect.")` и SQL-запрос ошибок за 24 часа для учёта `p3`.




* **Прайсинг и сравнение цен (`backend/app/models/pricing.py`, `backend/app/services/pricing_service.py`, `backend/app/models/repricer.py`)**:
* В `PriceCompareRow` (`backend/app/models/pricing.py`) добавить поля `ym_seller_price: float | None = None` и `ym_buyer_price: float | None = None`.


* В `PricingService.compare` (`backend/app/services/pricing_service.py`) добавить выборку `anyIf(p.seller_price, p.marketplace = 'ym') AS ym_seller_price`, `anyIf(p.buyer_price, p.marketplace = 'ym') AS ym_buyer_price`, `countIf(p.marketplace = 'ym') AS on_ym` и включить `row.ym_buyer_price` в расчёт `buyer_spread_pct`.


* В `default_fallback` (`backend/app/models/repricer.py`) и `_discount_usable` (`backend/app/services/pricing_service.py`) учесть `ym` по аналогии с `ozon` (`"seller_price"` при отсутствии измеренной скидки софинансирования, достаточно 1 продажи или прямого ответа `cofinance_price` из API Маркета).




* **Пуш остатков (`backend/app/services/integrations_service.py`)**:
* В `push_stock` добавить вызов `self._push_ym_stock(items)` при `marketplace is None or marketplace == "ym"` с использованием `YmActionsClient`.





---

## 10. Конкурентная разведка и браузерное расширение (`collectors/competitor/`, `browser_extension/`)

* **`collectors/competitor/`**:
* Добавить поддержку парсинга карточек и поисковой выдачи `market.yandex.ru` для сохранения в `raw_competitor_products`, `raw_competitor_prices`, `raw_competitor_search` с `marketplace = 'ym'`.




* **`browser_extension/` (`manifest.json`, `content.js`, `background.js`, `popup.js`, `protocol.js`)**:
* Добавить хост `*://*.market.yandex.ru/*` в `manifest.json`.


* В `content.js` и `protocol.js` добавить определение `marketplace = "ym"`, извлечение `product_id` (`marketSku`) со страницы товара и позиций из поисковой выдачи Маркета для отправки в `/api/v1/extension/positions` и `/api/v1/extension/competitor-price`.





---

## 11. Фронтенд (`frontend/src/`)

* **Фильтры и переключатели аккаунтов (`frontend/src/components/`)**:
* В `FiltersBar.jsx`, `AccountSwitcher.jsx`, `StatusChip.jsx`, `BuyerCardLink.jsx`, `SettingsPanel.jsx` добавить опцию Яндекс.Маркета (`value="ym"`, бейдж `Я.Маркет` / `YM`, генерацию внешней ссылки на карточку покупателя `[https://market.yandex.ru/product--slug/](https://market.yandex.ru/product--slug/){marketSku}` или поиск по `marketSku`).




* **Локализация (`frontend/src/utils/i18n.jsx`)**:
* Добавить переводы ключей для `ym` (RU/EN): названия маркетплейса, подсказки по токенам (`YM_API_KEY`, `YM_BUSINESS_ID`, `YM_CAMPAIGN_ID`), названия складов и типов софинансирования.




* **Страницы (`frontend/src/pages/`)**:
* `Pricing.jsx` и `Repricer.jsx`: добавить вкладку/фильтр `Я.Маркет`, столбцы `ym_seller_price` и `ym_buyer_price` в таблицу сравнения цен между маркетплейсами (`compare`), кнопку удержания цен (`keep_prices`) и импорта целевых цен для `ym`.


* `AdminActions.jsx`: добавить `ym` и его датасеты (`orders`, `sales`, `funnel`, `finance`) в форму запуска Backfill.


* `Dashboard.jsx`, `Sales.jsx`, `Stocks.jsx`, `Funnel.jsx`, `Ads.jsx`, `Finance.jsx`, `PnL.jsx`, `AbcXyz.jsx`, `Bidder.jsx`, `Reviews.jsx`, `Pim.jsx`, `History.jsx`, `Integrations.jsx`: убедиться, что цветовая кодировка графиков и фильтры корректно отображают серию данных `ym` наравне с `wb` и `ozon`.





---

## 12. Тестирование и контроль качества (`tests/` и CI)

* **Юнит-тесты (`tests/unit/`)**:
* Создать `tests/unit/test_ym_client.py` и `tests/unit/test_ym_parsers.py` по аналогии с `test_ozon_client.py`, `test_ozon_parsers.py`, `test_wb_client.py`, `test_wb_parsers.py`.


* Обновить `tests/unit/test_finance_parsers.py` (проверка маппинга транзакций `ym` в `common/finance.py`), `tests/unit/test_pricing.py` (сравнение цен 3 маркетплейсов и правила репрайсера для `ym`), `tests/unit/test_reviews.py` и `tests/unit/test_public_api_contract.py`.




* **Интеграционные и воркер-тесты (`tests/integration/`, `tests/worker_suite/`)**:
* Обновить `tests/worker_suite/test_task_registry.py` (проверка регистрации задач `tasks.ym_collect.*` и `ym_catalog_snapshot`) и `tests/worker_suite/test_marketplace_rules.py`.


* Обновить `tests/integration/test_sql_contracts.py` и `tests/integration/test_pipeline_smoke.py` для прогона пайплайна `raw_ym_* -> stg_* -> mrt_*`.




* **Финальная проверка перед коммитом**:
* Выполнить `python warehouse/apply_migrations.py verify` для проверки контрольных сумм миграций.


* Выполнить `ruff check .`, `ruff format --check .`, `mypy backend workers collectors automation warehouse scripts common` и `pytest -q`.


* Собрать фронтенд (`cd frontend && npm run build`) и прогнать тесты браузерного расширения (`node --test "browser_extension/tests/*.test.mjs"`).