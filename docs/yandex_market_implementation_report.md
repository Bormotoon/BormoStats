# Yandex Market parity remediation: implementation evidence

Дата: 2026-11-04

## Итог

Проведён сквозной аудит и доработка реализации Яндекс Маркета (`ym`) по мастер-плану `yandex_todo.md` и чек-листу `docs/yandex_market_parity_todo.md`. Кодовый, витринный, инфраструктурный и интерфейсный паритет с WB и Ozon приведён к полному соответствию в рамках репозитория и изолированных интеграционных тестов. Реальные записи в действующий кабинет маркетплейса, изменения production БД или ремонт production-истории не выполнялись (`MARKETPLACE_ACTIONS_ENABLED=false` по умолчанию). Dirty-изменения пользователя (включая `frontend/src/pages/SalesMonthly.jsx` и `frontend/src/pages/Taxes.jsx`) сохранены нетронутыми.

## Выполненные изменения и закрытые гэпы паритета

### 1. Сбор данных, очереди Celery, идемпотентность и безопасность действий
- `common/celery_config.py`, `Makefile`, `infra/docker/docker-compose.yml`, `scripts/run_os.sh`: выделена и подключена очередь `ym` для всех задач `tasks.ym_collect.*` и `tasks.history.ym_catalog_snapshot` по аналогии с `wb` и `ozon`.
- `workers/app/utils/marketplace_actions.py`, `workers/app/tasks/repricer.py`, `frontend/src/components/RuleControls.jsx`: внедрена двухфазная фиксация внешних изменений (`pending` перед вызовом API → `applied`/`failed` после ответа → `confirmed` при read-after-write сверке `reconcile_applied_actions`). Незавершённый `pending` (например, после сетевого таймаута или падения воркера) блокирует слепой повторный вызов репрайсера/биддера, а зафиксированный `failed` допускает повторную попытку.
- `workers/app/tasks/bidder.py` и `backend/app/models/bidder.py`: валидация строковых SKU YM (`1..255` символов), границ ставки `0.5–99.99%`, запрет неподдерживаемой стратегии `target_position`, проверка соответствия `account_id` настроенному магазину.
- `workers/app/tasks/ym_collect.py`: чтение и продвижение watermark по ключу датасета (`ym_ads`, `ym_finance`, `ym_funnel` и т.д.) с перекрытием, разбиение длинных периодов на окна, backfill без перезаписи recent watermark, защита бизнес-отчёта `shows-boost` в многомагазинном бизнесе (`YM_ALLOW_BUSINESS_WIDE_ADS` / owner-campaign).
- `backend/app/services/review_service.py` и `workers/app/tasks/reviews.py`: блокировка ручных и автоматических ответов при `MARKETPLACE_ACTIONS_ENABLED=false`, обогащение отзывов YM полями `offer_id`, `product_name` и каноническим `product_id` из `dim_product` через `_fill_ym_names`.

### 2. SQL-трансформации, витрины ClickHouse, каталог и финансовая сверка
- `workers/app/sql/transforms/sync_dim_product_catalog.sql` и `workers/app/sql/transforms/sync_dim_product_ym.sql`: синхронизация карточек YM из `hist_objects` и `raw_ym_offer_mappings` теперь сохраняет карточки без `marketSku` через детерминированный `cityHash64(offerId)` (вместо отбрасывания `marketSku > 0`) и извлекает `brand` (`vendor`) и `category`.
- `workers/app/sql/transforms/ym_ads_to_stg.sql`, `workers/app/sql/transforms/ym_funnel_to_stg.sql`, `workers/app/sql/transforms/ym_finance_to_stg.sql`, `workers/app/sql/marts/mrt_finance_daily_ym.sql`: унифицирован часовой пояс окна пересчёта `toDate(now(), 'Europe/Moscow') - %(days)s`.
- `workers/app/sql/marts/mrt_finance_daily_ym.sql`: операции перечисления средств (`payout != 0` или ключевые слова выплаты) выделены в категорию `payouts`, исключены из `net_accrued` и `details` во избежание занижения начислений, и агрегируются в колонку `payouts`.
- `workers/app/sql/marts/mrt_pnl_monthly.sql`: добавлен CTE `ym_netting_ads`, предотвращающий двойное вычитание расходов на «Буст продаж» YM в `operating_profit_rub`, когда буст одновременно присутствует в `united-netting` (`mrt_finance_daily.other`) и в `shows-boost` (`mrt_ads_daily.cost`).
- `workers/app/tasks/maintenance.py` и `workers/app/utils/data_quality.py`: все 10 таблиц `raw_ym_*` подключены к регламентной очистке `prune_old_raw` (с проверкой архивации в `hist_*`), а `raw_ym_orders` добавлена в проверку аномальных временных меток `_check_impossible_timestamps`.

### 3. Backend API, Frontend UI, локализация и инфраструктура
- `backend/app/api/v1/reviews.py`, `backend/app/services/review_service.py`, `frontend/src/pages/Reviews.jsx`: добавлена фильтрация отзывов по `account_id` в API и передача выбранного аккаунта из URL.
- `backend/app/api/v1/pim.py`, `frontend/src/pages/Pim.jsx`: добавлена валидация `^(wb|ozon|ym)$` в `PATCH /api/v1/pim/products/{marketplace}/{account_id}/{product_id}`, передача фильтра `marketplace` из URL и составной ключ карточки `${marketplace}:${account_id}:${product_id}`.
- `frontend/src/pages/AdminActions.jsx`, `frontend/src/utils/i18n.jsx`: добавлена кнопка и локализация (RU/EN) действия `backfill_ym_ads`, а также переводы всех 11 репозиториев `raw_ym_*` для страницы истории (`History.jsx`).
- `frontend/src/pages/Pricing.jsx`: сетка выбора маркетплейса расширена до 3 колонок (`sm:grid-cols-3`), подсказки скидок и целевой цены адаптированы под софинансирование и 1-sale расчёт YM.
- `backend/app/services/ai_service.py`: системный промпт генератора SEO-описаний обновлён для поддержки Wildberries, Ozon и Яндекс Маркета.
- `infra/nginx/templates/bormostats.conf.template`: в `Content-Security-Policy` (`img-src`) добавлены домены изображений карточек YM (`https://*.yandex.net`, `https://*.mds.yandex.net`).

## Выполненные команды и результаты проверок

- `.venv/bin/ruff check .` — All checks passed.
- `.venv/bin/ruff format --check .` — 289 files already formatted.
- `.venv/bin/mypy backend workers collectors automation warehouse scripts common` — Success: no issues found in 178 source files.
- `BORMOSTATS_TEST_TARGET=workers PYTHONPATH=workers:. .venv/bin/pytest tests/worker_suite -q` — 148 passed.
- `.venv/bin/pytest tests/integration -q` — 45 passed (включая новые тесты сверки P&L/выплат без двойного списания буста и синхронизации карточек YM без `marketSku`).
- `.venv/bin/pytest tests/unit -q` — 550 passed.
- `.venv/bin/python warehouse/apply_migrations.py verify` — `migration manifest OK`.
- `cd frontend && npm run build` — успешная production-сборка.
- `node --test "browser_extension/tests/*.test.mjs"` — 5 passed.

## Оставшиеся внешние ограничения (требуют реального кабинета)

- Контрольная сверка сумм на реальном кабинете продавца по всем моделям работы (`FBY`, `FBS`, `DBS`, `Express`) и проверка живых ответов API на нестандартных операциях.
- Для заказов, впервые импортированных уже после полного возврата без ранее сохранённого снимка `DELIVERED` и без строк в `raw_ym_finance`, Partner API не отдаёт историческую дату доставки в текущем снимке заказа — такие заказы явно помечаются `source_quality = 'return_without_observed_delivery'` без генерации фиктивной продажи.
- Partner API не предоставляет эндпоинта снимка баланса счёта, аналогичного WB/Ozon, поэтому `ym_balance_snapshot` возвращает `status = "unsupported"`.
