# Тотальный аудит BormoStats

Дата аудита: 24 сентября 2026 г.  
Область: backend, workers, collectors, ClickHouse-модель и миграции, frontend, Docker/Compose, CI/CD, безопасность, документация, тесты и операционные скрипты.

## 1. Краткое резюме

Проект имеет хорошо очерченную архитектуру и рабочий базовый набор тестов, но сейчас находится в состоянии, при котором production-запуск и часть новых функций нельзя считать надёжными:

- `pytest` проходит: **64 теста успешно**.
- Сборка frontend проходит.
- `ruff check`, форматирование и строгий `mypy` не проходят.
- Обнаружены минимум две ошибки в SQL-форматировании, которые могут приводить к падению runtime-операций.
- Docker/Compose-путь запуска из `make up` сломан из-за неверного пути к `.env`.
- Документация и скрипты ссылаются на отсутствующий `.env.example`.
- Multi-tenant авторизация реализована непоследовательно: часть запросов использует `default` или параметры клиента вместо организации текущего пользователя.
- В frontend и зависимости выявлены 5 npm-уязвимостей: 4 high и 1 moderate.
- Несколько заявленных автоматизаций (bidder/repricer) фактически только логируют изменение, но не вызывают API маркетплейса.
- CI допускает прохождение supply-chain проверок даже при найденных уязвимостях.

Рекомендуемый порядок: сначала исправить блокирующие ошибки запуска и runtime, затем закрыть tenant isolation/auth, после этого привести CI и миграции к безопасной эксплуатационной модели.

## 2. Проверки, выполненные во время аудита

| Проверка | Результат |
|---|---|
| `make test` | PASS, 64 теста |
| `make lint` | FAIL, 86 ошибок Ruff |
| `make format-check` | FAIL, 14 файлов требуют форматирования |
| `make typecheck` | FAIL, 56 ошибок MyPy в 5 файлах |
| `npm ci && npm run build` | PASS, production bundle собран |
| `npm audit` | FAIL/внимание: 5 уязвимостей, 4 high, 1 moderate |
| Docker Compose config | Не проверен штатно: в репозитории отсутствует `.env`, а `make up` дополнительно содержит ошибку пути к env-файлу |

Проверки выполнялись без внесения исправлений в исходный код. В рабочей копии перед началом изменений незакоммиченных файлов не было.

## 3. Критические проблемы

### C-01. `make up` передаёт Docker Compose неверный путь к `.env`

- **Файл:** `scripts/run_local.sh:29-32`
- **Проблема:** скрипт сначала находится в корне, затем делает `cd infra/docker`, после чего вызывает `docker compose --env-file ../.env`. Из каталога `infra/docker` этот путь указывает на `infra/.env`, а настоящий файл находится в корне проекта.
- **Эффект:** рекомендованный `make up` не находит конфигурацию окружения и не запускает стек.
- **Исправление:** использовать абсолютный путь `--env-file "$ROOT_DIR/.env"`, не менять рабочий каталог либо передавать `-f "$COMPOSE_FILE"`.
- **Проверка после исправления:** `cp .env.dev.example .env`, затем `make docker-config` и `make up` на чистом Docker-хосте.

### C-02. Скрипты и README используют отсутствующий `.env.example`

- **Файлы:** `README.md:173`, `README.ru.md:173`, `scripts/install.sh:24`, `scripts/run_local.sh:9`, `scripts/bootstrap.sh:118`.
- **Проблема:** в корне есть `.env.dev.example`, `.env.stage.example`, `.env.prod.example`, но `.env.example` отсутствует.
- **Эффект:** Docker quick start, OS install и bootstrap завершаются ошибкой на шаге копирования шаблона.
- **Исправление:** либо добавить canonical `.env.example` с безопасными placeholder-значениями, либо везде явно выбирать `.env.dev.example` и документировать выбор окружения. Лучше сделать `make init ENV=dev|stage|prod` с проверкой обязательных переменных.

### C-03. Runtime-ошибка `.format()` в `BidderService.sync_campaigns`

- **Файл:** `backend/app/services/bidder_service.py:148-151`.
- **Проблема:** строка содержит placeholders `{cid}`, `{mp}`, `{aid}` и другие, но `.format()` получает только `cols=_CAMP_COLS`. Ruff выдаёт F524, MyPy — ошибки `Cannot find replacement for named format specifier`.
- **Эффект:** синхронизация рекламных кампаний падает до выполнения ClickHouse-команды.
- **Исправление:** не применять `.format()` ко всей SQL-строке. Вынести список колонок в безопасную f-string-часть, а placeholders ClickHouse экранировать или использовать константу вида `... VALUES (...)` без Python `.format` для параметров.
- **Тест:** добавить unit-тест, который вызывает `sync_campaigns` на fake client и проверяет сформированную команду и parameters.

### C-04. Runtime-ошибка `.format()` в `InsightsService.update_task`

- **Файл:** `backend/app/services/insights_service.py:42-47`.
- **Проблема:** аналогичная ошибка: `.format(cols=_TASK_COLS)` пытается интерпретировать ClickHouse-параметры `tid`, `oid`, `status` и т.д. как Python placeholders.
- **Эффект:** PATCH задачи insights падает при обновлении статуса.
- **Исправление:** разделить форматирование списка колонок и ClickHouse bind-параметров; добавить API-тест для переходов `open → resolved` и `resolved → open`.

### C-05. Worker tasks импортируют несуществующий/неправильно типизированный runtime-контракт

- **Файлы:** `workers/app/tasks/bidder.py`, `workers/app/tasks/repricer.py`, `workers/app/tasks/insights.py`.
- **Проблема:** MyPy сообщает `Module "app.celery_app" has no attribute "app"` и `Cannot find implementation ... app.runtime`. При этом в `Makefile` используется `app.celery_app:celery_app`, а task-файлы импортируют `app`.
- **Эффект:** строгая типизация не отражает реальный import contract; отдельный запуск/импорт задач может расходиться с запуском Celery.
- **Исправление:** унифицировать имя Celery-объекта (`celery_app`), явно экспортировать его в одном модуле, исправить import `get_ch_client/new_run_context` на существующий модуль и добавить smoke-тест `python -c 'import ...'` для всех task-модулей.

## 4. Высокий приоритет: безопасность и изоляция данных

### H-01. Аналитические endpoints не требуют аутентификации

- **Файлы:** `backend/app/api/v1/sales.py`, `stocks.py`, `funnel.py`, `ads.py`, `kpis.py`; аналогичный pattern виден в metrics-сервисах.
- **Проблема:** endpoints получают ClickHouse client, но не `CurrentUserDependency` и не `require_admin_key_or_org_role`.
- **Эффект:** при доступе к backend можно читать продажи, остатки, рекламу и KPI без API key. На reverse proxy публичным entry point является весь backend.
- **Исправление:** ввести единый auth dependency для read-only analytics. Технический health endpoint оставить публичным, `/metrics` ограничить сетью/отдельным listener или bearer auth. Для обратной совместимости предусмотреть явный `PUBLIC_READ_API=false`.

### H-02. Организация пользователя не используется во многих mutating/read endpoints

- **Файл:** `backend/app/api/v1/integrations.py:46,55,73`.
- **Проблема:** `list_subscriptions` и `list_logs` жёстко используют `"default"`; `create_subscription` не передаёт organization текущего пользователя. `CurrentUserDependency` импортирован, но не используется.
- **Эффект:** пользователи разных организаций могут видеть/создавать webhook-данные не в своей организации; это нарушение tenant isolation.
- **Исправление:** dependency должен возвращать текущего пользователя/организацию, сервисы должны принимать `organization_id` только из auth context. Удалить возможность передавать tenant через body/query без серверной проверки.

### H-03. Проверка роли сравнивает enum через числовое значение без явной политики

- **Файл:** `backend/app/core/deps.py:184-190`.
- **Проблема:** доступ разрешается при `actual_role.value <= min_role.value`. Это хрупко: порядок Enum становится частью security policy, а отсутствие записи маскируется ролью viewer.
- **Исправление:** использовать явный набор разрешённых ролей/метод `role_allows(actual, required)`, тесты для каждой пары ролей и отдельное поведение для отсутствующего membership (`403`, не viewer).

### H-04. API keys хранятся в ClickHouse в открытом виде

- **Файлы:** `warehouse/migrations/0011_collaboration.sql:6`, `backend/app/core/deps.py:125-141`.
- **Проблема:** `dim_user.api_key String`, затем запрос сравнивает plaintext key.
- **Эффект:** утечка дампа/доступ read-user раскрывает действующие ключи; ключи также могут попадать в админские экспортные операции.
- **Исправление:** хранить только Argon2id/scrypt hash, проверять через constant-time verify. Добавить `key_id`, `created_at`, `last_used_at`, срок действия и отзыв. Для master admin key минимум использовать `secrets.compare_digest` и ограничить его по сети.

### H-05. Webhook secrets хранятся plaintext и отсутствуют полноценные webhook runtime-механизмы

- **Файл:** `warehouse/migrations/0020_webhooks.sql:9`, `backend/app/api/v1/integrations.py`.
- **Проблема:** secret записывается напрямую; endpoint управления подписками не показывает реализацию доставки, подписи, retries, replay protection или rotation.
- **Исправление:** хранить secret зашифрованным/внешнем secret store, показывать только один раз, подписывать payload HMAC с timestamp, добавить idempotency key, retry с backoff, dead-letter статус, SSRF-защиту URL и allowlist/private-IP блокировку.

### H-06. Принимаемые extension payloads используют `dict[str, Any]` без схемы и лимитов

- **Файл:** `backend/app/api/v1/extension.py:15,41`.
- **Проблема:** нет Pydantic-моделей, ограничений размера списка, длины keyword/name, диапазона position/price и валидации marketplace.
- **Эффект:** плохие данные, дорогостоящие N отдельных INSERT-команд, риск DoS и слабая наблюдаемость ошибок.
- **Исправление:** строгие модели с `Field`-лимитами, максимум batch size, одна bulk insert операция, идемпотентный event id и понятный partial-failure контракт.

### H-07. Redis запускается без обязательного пароля по умолчанию

- **Файлы:** `infra/docker/docker-compose.yml:86`, `.env.dev.example:21-22`.
- **Проблема:** `--requirepass ${REDIS_PASSWORD:-}` допускает пустой пароль.
- **Исправление:** в production validation запрещать пустой Redis password, использовать ACL вместо одного пароля и TLS/изолированную сеть. Аналогично запретить bootstrap ClickHouse с пустым паролем в production.

### H-08. CI supply-chain проверки не блокируют сборку

- **Файл:** `.github/workflows/ci.yml:78-80,112-132`.
- **Проблема:** `pip-audit`, Grype и scan actions используют `continue-on-error: true`/`fail-build: false`.
- **Эффект:** pipeline зелёный даже при известных high vulnerabilities; результаты не являются gate.
- **Исправление:** ввести allowlist с expiry date для исключений, fail на high/critical fixed vulnerabilities, сохранять SARIF в Security tab и разделить advisory job от blocking release job.

## 5. Высокий приоритет: бизнес-логика и корректность данных

### H-09. Bidder и repricer не выполняют заявленное изменение на маркетплейсе

- **Файлы:** `workers/app/tasks/bidder.py:72-79`, `workers/app/tasks/repricer.py:80-87`.
- **Проблема:** `_adjust_bid` и `_adjust_price` только пишут `LOGGER.info`; вызова WB/Ozon API нет.
- **Эффект:** интерфейс и README заявляют автоматическое управление ставками/ценами, но фактическое состояние маркетплейса не изменяется. Это особенно опасно для автоматизации: оператор может считать, что правило применено.
- **Исправление:** реализовать реальные marketplace clients с dry-run режимом, idempotency, rate limits, audit trail, before/after, response status и circuit breaker. До реализации переименовать функции/документацию в `preview`/`simulation`.

### H-10. Генерация insights неидемпотентна и создаёт дубликаты ежедневно

- **Файл:** `workers/app/tasks/insights.py:39-43,60,91,121`.
- **Проблема:** каждый запуск генерирует новый короткий UUID и вставляет новую задачу; проверки уже существующей открытой рекомендации нет.
- **Эффект:** очередь задач и Telegram digest будут расти с дубликатами одного и того же товара/кампании.
- **Исправление:** добавить `dedupe_key` (organization, trigger, marketplace, account, product/campaign, active window), уникальный логический ключ и upsert/merge. Для ClickHouse ReplacingMergeTree проектировать deterministic version и контролировать eventual consistency.

### H-11. Insights игнорирует `organization_id` в SQL-триггерах

- **Файл:** `workers/app/tasks/insights.py:52-57,82-88,113-118`.
- **Проблема:** цикл перебирает организации, но SQL-запросы к mart-таблицам не фильтруют `org_id`; одна и та же строка может быть сгенерирована для каждой организации.
- **Эффект:** cross-tenant leakage/неверные рекомендации и дубликаты.
- **Исправление:** включить organization_id в marts и во все WHERE/JOIN/GROUP BY, добавить multi-tenant integration test с двумя организациями.

### H-12. `task_id` и многие идентификаторы обрезаются до 8 символов

- **Файлы:** `workers/app/tasks/insights.py`, `backend/app/services/bidder_service.py:68`, `backend/app/services/...`.
- **Проблема:** `str(uuid.uuid4())[:8]` увеличивает вероятность коллизий и затрудняет трассировку.
- **Исправление:** хранить полный UUID/ULID; если нужен короткий display id, не использовать его как primary/business key.

### H-13. Миграционный runner небезопасен при параллельном запуске и rollback

- **Файл:** `warehouse/apply_migrations.py`.
- **Проблемы:** нет distributed lock; два deploy-процесса могут применить одну миграцию; запись версии добавляется после нескольких DDL без транзакционной гарантии; rollback использует `ALTER TABLE ... DELETE`, что в ClickHouse асинхронно; `--rollback` без аргумента трудно отличить от отсутствия флага из-за `args.rollback is not None`.
- **Исправление:** lock через ClickHouse/Redis, журнал состояний `started/applied/failed`, checksum SQL, запрет изменения уже применённой миграции, отдельная команда `rollback --target`, проверка наличия rollback и postcondition checks. Rollback для production делать как forward-fix.

### H-14. Время хранится как naive UTC через `datetime.utcnow()`

- **Файлы:** services и workers.
- **Проблема:** в ClickHouse пишутся naive datetime, при наличии `TZ` и локальных отчётов легко получить смещение/неоднозначность.
- **Исправление:** использовать timezone-aware UTC (`datetime.now(timezone.utc)`), зафиксировать типы/контракт в модели, преобразование в пользовательскую TZ выполнять на границе API/UI.

## 6. Средний приоритет: качество кода и тестирование

### M-01. 86 ошибок Ruff и 14 неформатированных файлов

Основные категории: unused imports, длинные строки, unsorted imports, unused variables `run_id`, ambiguous Cyrillic warnings и один потенциально важный F524. `make check` поэтому не является рабочим quality gate.

**Решение:** сначала исправить runtime F524 вручную, затем `ruff check . --fix`, `ruff format .`, после чего вручную проверить diff и закрепить pre-commit hook.

### M-02. 56 ошибок строгой типизации

Проблемы сосредоточены в bidder/repricer/insights и включают отсутствующие модули, untyped Celery decorators, `dict[str, object]` variance и unsafe casts из ClickHouse rows.

**Решение:** описать протоколы для ClickHouse client/result rows, типизировать task bind self, добавить typed row mappers, вынести общие task helpers и не ослаблять `strict` глобально.

### M-03. Тесты покрывают в основном unit/config/contract, но не критические сценарии

Отсутствуют или недостаточны тесты для:

- реального SQL command generation для bidder/insights/PIM/integrations;
- API auth и tenant isolation для каждого endpoint;
- duplicate/dedup behavior insights;
- migration upgrade/rollback на ClickHouse;
- Celery task import, retry и идемпотентности;
- webhook signature/retry/SSRF защиты;
- frontend accessibility и базовых пользовательских flows;
- browser extension permissions и content-script поведения.

**Решение:** добавить integration matrix: два tenant, два marketplace, admin/user/viewer, positive/negative paths, ClickHouse container в CI.

### M-04. Backend использует один cached ClickHouse client без явной проверки жизненного цикла

- **Файл:** `backend/app/core/deps.py:24-53`.
- **Проблема:** `lru_cache` возвращает singleton client; нет startup/shutdown hook, health/pool metrics или reconnect policy.
- **Решение:** управлять client через lifespan FastAPI, закрывать его на shutdown, добавить bounded query timeout и метрики ошибок/latency.

### M-05. `/ready` создаёт и закрывает новые clients на каждый запрос

- **Файл:** `backend/app/main.py:105-130`.
- **Проблема:** readiness check может создавать нагрузку на ClickHouse/Redis при частом health polling.
- **Решение:** короткий timeout, cache результата на несколько секунд, отдельные liveness/readiness/dependency endpoints и мониторинг latency.


- **Файл:** `backend/app/main.py:204-207`.
- **Проблема:** scraping Prometheus может блокироваться ClickHouse-запросами.
- **Решение:** обновлять operational gauges периодической задачей/cache, а handler делать O(1); не публиковать внутренние метрики без сетевого ограничения.


- **Файл:** `frontend/src/utils/api.js:13,26-30`; UI пишет тот же ключ в `Layout.jsx`.
- **Проблема:** любой XSS в SPA или подключённом origin получает master key; при этом нет logout/rotation/status.
- **Решение:** предпочтительно серверная сессия с HttpOnly Secure SameSite cookie и CSRF protection. Если API key оставляется, не использовать master key для UI, выдавать scoped short-lived token и добавить явную кнопку очистки.


- **Файл:** `frontend/src/utils/api.js:33-35,68`.
- **Проблема:** пользовательский/скомпрометированный localStorage может направить ключ на внешний origin.
- **Решение:** в production отключить произвольный API base или разрешать только origin из конфигурации; валидировать protocol/host и предупреждать о cross-origin отправке credentials.


- **Файл:** `infra/nginx/nginx.conf:30-34`.
- **Проблема:** HSTS имеет смысл только в HTTPS-ответах; при этом self-signed certificate и `TLS_SERVER_NAME` не используются для SAN.
- **Решение:** выдавать HSTS только из TLS server, генерировать cert с SAN, для production использовать доверенный cert/ACME, добавить proxy timeouts/body limits и rate limit на admin/webhook routes.


- README обещает `https://localhost:18443/ui/`, скрипт `run_local.sh` печатает HTTP URL, а текущий proxy HTTP перенаправляет на HTTPS.
- README указывает `WB_STATISTICS_API_KEY`, конфигурация использует `WB_TOKEN_STATISTICS`.
- Русский README утверждает Material Design 3, исходники используют Tailwind CSS и собственные CSS tokens.

**Решение:** генерировать документацию из актуального `.env` contract/Compose, добавить smoke-проверку ссылок и команд quick start.

## 7. Зависимости и supply chain

### M-11. npm audit: 5 уязвимостей

Результат на момент аудита:

- `react-router-dom`/`react-router` в диапазоне `7.12.0–7.18.1` — high, CSRF/RSC advisory; текущий диапазон `^7.18.0` допускает уязвимую версию.
- `postcss <= 8.5.22` — high advisory; текущая зависимость `^8.5.15` допускает уязвимые версии.
- `nanoid < 3.3.18` — 2 high advisories транзитивно.
- `@tailwindcss/postcss 4.3.1` — moderate.

**Решение:** обновить lockfile до версий с fix, проверить совместимость Vite/Tailwind/React Router, затем `npm audit`, build и smoke tests. Не применять `npm audit fix --force` без review major changes.

### M-12. Python requirements дублируют транзитивные зависимости

`requirements.txt` содержит большой вручную зафиксированный список, включая `starlette`, `pydantic_core`, `typing_extensions`, `urllib3` и другие зависимости верхнего уровня. Это усложняет обновления и может скрывать конфликт с прямыми constraints.

**Решение:** оставить в direct requirements только прямые зависимости, генерировать lock/constraints (`uv lock`, pip-tools или аналог), запускать регулярное обновление Dependabot с CI.

### M-13. GitHub Actions actions не зафиксированы по commit SHA

В workflow используются tags `actions/checkout@v7`, `actions/setup-python@v5`, `anchore/*@v0`. Для supply-chain security лучше pin на commit SHA с Renovate/Dependabot обновлениями.

## 8. Производительность и эксплуатация

1. **Extension batch INSERT:** сейчас выполняется один ClickHouse command на каждый item. Перейти на bulk insert и ограничить batch.
2. **ClickHouse `FINAL`:** множество API-запросов используют `FINAL`, что дорого на больших таблицах. Рассмотреть projections/materialized views, правильный `ReplacingMergeTree` version column и периодический optimize только по необходимости.
3. **Счётчики без pagination total:** `build_paginated_response` возвращает page, но нужно проверить, есть ли дешёвый total/count и cursor pagination для больших marts.
4. **Celery concurrency:** значение `--concurrency=4` жёстко задано. Вынести в env, разделить queues для API collectors, transforms и mutating marketplace actions.
5. **Backpressure и quotas:** добавить per-marketplace rate limiter, retry-after, circuit breaker, dead-letter queue и ограничение размера backfill.
6. **Наблюдаемость:** correlation/request id не проходит единообразно через API → Celery → collector → warehouse. Добавить trace/span id и task id во все structured logs.
7. **Data quality:** добавить freshness, row count, null rate, duplicate rate, schema drift и marketplace API lag как Prometheus metrics и alert rules.
8. **Backups:** compose volumes объявлены, но автоматического backup/restore test для ClickHouse, Redis и Metabase не видно. Добавить расписание, retention, encryption и регулярный restore drill.
9. **Deployment:** добавить graceful shutdown, worker termination policy, rolling migration protocol и совместимость старой/новой схемы при zero-downtime deploy.
10. **Secrets:** использовать Docker secrets/secret manager, не передавать secret через командную строку там, где он может оказаться в process metadata.

## 9. Что улучшить в архитектуре

### 9.1. Единая модель идентичности

Сейчас существуют master admin key, user API key, organization role и параметры `account_id`/`organization_id`, но правила смешаны. Нужен единый `AuthContext`:

```text
principal_id
organization_id
role
scopes
auth_method
```

Все сервисные методы должны принимать `AuthContext`, а не доверять tenant-полям из запроса. Для системных задач использовать отдельный service principal.

### 9.2. Репозитории вместо SQL в endpoint/service вперемешку

Вынести ClickHouse queries в repositories с typed result mappers. Это уменьшит дублирование SQL, позволит централизовать tenant filters, timeouts и query metrics, а также сделает unit-тесты менее хрупкими.

### 9.3. Контракт миграций

Добавить manifest для каждой миграции: version, checksum, dependencies, destructive flag, rollback status. CI должен поднять ClickHouse с нуля, применить все миграции, проверить schema contract, затем прогнать upgrade со старой fixture-схемой.

### 9.4. Разделить preview и side effects

Bidder/repricer/integrations должны иметь:

- `dry_run` по умолчанию для новых правил;
- отдельное разрешение `execute:marketplace`;
- approval/audit event перед изменением цены/ставки;
- idempotency key и хранение результата вызова;
- аварийный global kill switch.

## 10. Что добавить

1. OpenAPI schema endpoint в защищённом режиме и версионирование API contract.
2. `/health/live`, `/health/ready`, `/health/dependencies` с различными SLA.
3. Scoped user sessions, passwordless key rotation и revoke-all.
4. Audit log для каждого admin/mutating действия: actor, organization, endpoint, object, before/after, reason, request id.
5. UI: статус текущего пользователя/организации, logout, key rotation, last sync/freshness, data source errors.
6. UI: фильтры по организации/магазину с серверной проверкой, экспорт CSV/XLSX с async job и notification.
7. Webhook: test delivery, rotate secret, retry history, replay blocked, endpoint verification.
8. Data catalog с описанием метрик, источника, формулы и допустимой задержки.
9. Alerting: ingestion stalled, ClickHouse disk, Redis memory, task retry storm, API quota, stale marts.
10. E2E Playwright smoke suite для login/settings/dashboard/admin denial.
11. Browser extension: explicit API origin configuration, permission minimization, CSP, versioned message protocol and signed release artifacts.
12. Release process: semantic versioning, CHANGELOG, migration notes, SBOM artifact retention, signed container images.

## 11. План исправлений

### P0 — перед любым production использованием

1. Исправить `.env` path и добавить/выбрать `.env.example`.
2. Исправить два `.format()` runtime bug.
3. Починить worker imports/проверить импорт всех Celery tasks.
4. Закрыть analytics endpoints auth и исправить organization propagation в integrations/insights.
5. Заблокировать пустые Redis/production passwords.
6. Обновить npm vulnerabilities.

### P1 — ближайший спринт

1. Сделать `make check` зелёным: Ruff, format, MyPy.
2. Перевести user API keys на hash + rotation/revoke.
3. Сделать insights idempotent и добавить org filter.
4. Добавить integration tests для ClickHouse migrations, auth matrix и task SQL.
5. Включить blocking supply-chain gates.
6. Разделить dry-run и реальные bidder/repricer side effects.

### P2 — укрепление продукта

1. Repository layer и единый AuthContext.
2. Webhook delivery engine с HMAC/retries/SSRF protection.
3. Async export, data-quality metrics, freshness dashboards.
4. Backup/restore drills, disaster recovery automation и release rollback strategy.
5. E2E frontend/extension tests, accessibility review и performance budgets.

## 12. Definition of Done после исправлений

- `make check` проходит без ошибок.
- `npm ci && npm audit --audit-level=high && npm run build` проходит.
- `docker compose ... config -q` проходит из корня с documented env template.
- Чистая установка по README проходит с нуля.
- Migration smoke: install, upgrade, schema verification, backup/restore test.
- Ни один analytics/mutating endpoint не принимает tenant из тела вместо auth context.
- Два tenant integration tests доказывают отсутствие cross-tenant read/write.
- Bidder/repricer имеют проверенный dry-run и audit trail; реальные API calls покрыты mock contract tests.
- CI блокирует fixed high/critical vulnerabilities и сохраняет SBOM/SARIF.
- Есть актуальный CHANGELOG и release checklist.
