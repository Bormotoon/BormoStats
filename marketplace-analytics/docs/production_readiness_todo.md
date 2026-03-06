# Production Readiness TODO

Дата создания: 2026-03-06

Связанный документ: `docs/production_readiness_plan.md`

## Как использовать

- `[ ]` не начато
- `[~]` в работе
- `[x]` завершено
- Закрывать задачу только после выполнения всех подпунктов и критериев проверки

## Phase P0: Security, Correctness, Release Blockers

### P0-01. Убрать insecure defaults и placeholder values

- [x] Удалить рабочие/опасные дефолты из [.env.example](/home/borm/VibeCoding/BormoStats/marketplace-analytics/.env.example)
- [x] Убрать `ADMIN_API_KEY=change_me` как рабочий fallback из [config.py](/home/borm/VibeCoding/BormoStats/marketplace-analytics/backend/app/core/config.py)
- [x] Убрать hardcoded ClickHouse admin credentials из [001_users.sql](/home/borm/VibeCoding/BormoStats/marketplace-analytics/infra/docker/clickhouse/initdb/001_users.sql)
- [x] Добавить startup validation для placeholder credentials в backend
- [x] Добавить startup validation для placeholder credentials в worker
- [x] Обновить bootstrap flow, чтобы он требовал явной безопасной конфигурации
- [x] Обновить README и quickstart под новый secrets flow

Критерии закрытия:

- [x] backend не стартует с placeholder admin key
- [x] worker не стартует с placeholder marketplace credentials
- [x] в репозитории нет "боевых" секретов по умолчанию

### P0-02. Ограничить admin control plane

- [x] Удалить или закрыть произвольный `/api/v1/admin/run-task`
- [x] Вынести разрешенные admin-действия в явный whitelist
- [x] Создать отдельные typed request models для каждого admin action
- [x] Ограничить допустимые параметры `days`, `marketplace`, `dataset`
- [x] Добавить audit logging для admin operations
- [x] Обновить UI под новую модель admin actions
- [x] Обновить CLI scripts, если они завязаны на `run-task`

Критерии закрытия:

- [x] нельзя отправить произвольный Celery task через API
- [x] все admin операции валидируются Pydantic-моделями
- [x] все admin вызовы логируются в понятном формате

### P0-03. Убрать хранение admin key в localStorage

- [x] Перестать сохранять admin key в `localStorage` в [app.js](/home/borm/VibeCoding/BormoStats/marketplace-analytics/backend/app/ui/app.js)
- [x] Перевести хранение ключа на in-memory/session-only модель
- [x] Добавить явный UX для повторного ввода ключа после reload
- [x] Обновить UI help text и документацию

Критерии закрытия:

- [x] admin key не сохраняется между перезапусками браузера
- [x] UI не оставляет секрет в persistent browser storage

### P0-04. Исправить retry semantics и circuit breaker

- [x] Разделить retryable и non-retryable ошибки в [http_client.py](/home/borm/VibeCoding/BormoStats/marketplace-analytics/collectors/common/http_client.py)
- [x] Убрать retry для `CircuitOpenError`
- [x] Убрать retry для non-retryable `4xx`
- [x] Оставить retry только для `429`, `5xx` и network/transport errors
- [x] Привести logging к явному разделению причин retry/fail-fast
- [x] Добавить unit tests на `429`
- [x] Добавить unit tests на `500`
- [x] Добавить unit tests на `400/401/403`
- [x] Добавить unit tests на open circuit path

Критерии закрытия:

- [x] `429` и `5xx` повторяются по policy
- [x] `4xx` завершаются без лишних retry loops
- [x] circuit breaker действительно "режет" поток запросов при open state

### P0-05. Исправить парсинг Ozon cancellation timestamps

- [x] Найти корректное поле времени отмены в payload Ozon postings
- [x] Исправить mapping в [parsers.py](/home/borm/VibeCoding/BormoStats/marketplace-analytics/collectors/ozon/parsers.py)
- [x] Добавить fixture cancelled posting в тесты
- [x] Добавить regression test на `canceled_at`
- [x] Проверить совместимость со старыми payload variants

Критерии закрытия:

- [x] cancelled postings пишут корректный `canceled_at`
- [x] тест на cancelled payload проходит стабильно

### P0-06. Сериализовать destructive rebuild tasks

- [x] Добавить lock для `transform_all_recent`
- [x] Добавить lock для `transform_backfill_days`
- [x] Добавить lock для `build_marts_recent`
- [x] Добавить lock для `build_marts_backfill_days`
- [x] Исключить одновременный запуск конфликтующих rebuild jobs
- [x] Пересобрать расписание beat так, чтобы marts не стартовали поверх transform
- [x] Добавить логирование skipped/conflicting launches
- [x] Добавить integration test на serialization rebuild jobs

Критерии закрытия:

- [x] нет параллельных `DELETE + INSERT` конфликтов в `stg_*`
- [x] нет параллельных `DELETE + INSERT` конфликтов в `mrt_*`
- [x] marts запускаются только после консистентного transform stage

### P0-07. Сделать locks продлеваемыми

- [x] Добавить heartbeat/renew для Redis locks
- [x] Обновить API lock utils под renewable lifecycle
- [x] Встроить renew в long-running collector/backfill tasks
- [x] Добавить telemetry по длительности владения lock
- [x] Добавить tests на renew path
- [x] Добавить tests на safe release после renewal

Критерии закрытия:

- [x] долгий backfill не теряет эксклюзивность после истечения начального TTL
- [x] release чужого lock невозможен

### P0-08. Довести CI до полностью зеленого состояния

- [x] Закрыть все текущие `ruff` ошибки
- [x] Закрыть все текущие `black --check` расхождения
- [x] Закрыть все текущие `mypy` ошибки
- [x] Устранить import-path проблемы в mypy для `backend/app` и `workers/app`
- [x] Устранить untyped decorator issues вокруг Celery tasks
- [x] Добавить missing type stubs или правильные mypy overrides
- [x] Прогнать `pytest` на чистом окружении
- [x] Убедиться, что CI workflow повторяет локальные quality gates

Критерии закрытия:

- [x] `ruff check .` зеленый
- [x] `black --check .` зеленый
- [x] `mypy backend workers collectors automation warehouse scripts` зеленый
- [x] `pytest -q` зеленый
- [x] GitHub Actions workflow зеленый

### P0-09. Починить migration smoke workflow

- [x] Исправить host/port assumptions в [ci.yml](/home/borm/VibeCoding/BormoStats/.github/workflows/ci.yml)
- [x] Убедиться, что `.env.example` не ломает GitHub runner networking
- [x] Исправить bootstrap переменные для CI ClickHouse endpoint
- [x] Проверить `apply_migrations.py` в CI runtime
- [x] Добавить явную проверку ключевых таблиц после migrations
- [x] Проверить cleanup docker services в `always()`

Критерии закрытия:

- [x] migration smoke job стабильно проходит на GitHub Actions
- [x] migrations реально применяются, а не падают на неверном host/port

### P0-10. Пиновать зависимости и образы

- [x] Зафиксировать версии Python dependencies в [requirements.txt](/home/borm/VibeCoding/BormoStats/marketplace-analytics/requirements.txt)
- [x] Зафиксировать версии dev dependencies
- [x] Пиновать Docker base images в [backend/Dockerfile](/home/borm/VibeCoding/BormoStats/marketplace-analytics/backend/Dockerfile)
- [x] Пиновать Docker base images в [workers/Dockerfile](/home/borm/VibeCoding/BormoStats/marketplace-analytics/workers/Dockerfile)
- [x] Заменить `latest` на фиксированные версии в [docker-compose.yml](/home/borm/VibeCoding/BormoStats/marketplace-analytics/infra/docker/docker-compose.yml)
- [x] Зафиксировать policy обновления зависимостей в docs

Критерии закрытия:

- [x] docker images reproducible
- [x] Python environment reproducible
- [x] redeploy не меняет behavior без изменения кода

## Phase P1: Operational Hardening

### P1-01. Экспортировать worker и beat metrics

- [x] Выбрать модель экспорта: отдельный endpoint или sidecar exporter
- [x] Поднять metrics endpoint для worker
- [x] Поднять metrics endpoint для beat
- [x] Добавить scrape config/документацию для Prometheus
- [x] Проверить экспорт `task_duration_seconds`
- [x] Проверить экспорт `task_runs_total`
- [x] Проверить экспорт `watermark_lag_seconds`
- [x] Проверить экспорт `empty_payload_total`

Критерии закрытия:

- [x] метрики worker и beat доступны снаружи
- [x] operational dashboards могут их читать

### P1-02. Настроить alerting и dashboards

- [x] Определить alert rules для failed task runs
- [x] Определить alert rules для stale watermarks
- [x] Определить alert rules для empty payload anomalies
- [x] Определить alert rules для Redis saturation
- [x] Определить alert rules для ClickHouse disk / readiness
- [x] Подготовить базовый operational dashboard
- [x] Подготовить dashboard по ingestion freshness

Критерии закрытия:

- [x] alerts описаны, настроены и тестово срабатывают
- [x] есть dashboard для ежедневной эксплуатации

### P1-03. Ограничить рост Redis/Celery metadata

- [x] Решить, нужны ли task results вообще
- [x] Если не нужны, включить `task_ignore_result = true`
- [x] Если нужны, добавить expiry/retention policy
- [x] Проверить поведение admin workflows после изменения
- [x] Обновить docs по Redis retention

Критерии закрытия:

- [x] Redis не накапливает бесконечно task metadata
- [x] admin/API flow не ломается после изменения result policy

### P1-04. Harden Docker runtime

- [x] Перевести backend container на non-root user
- [x] Перевести worker container на non-root user
- [x] Добавить `restart` policies в compose
- [x] Добавить resource limits / reservations
- [x] Добавить/уточнить healthchecks для backend, worker, beat
- [x] Рассмотреть read-only filesystem где возможно
- [x] Обновить docs по runtime assumptions

Критерии закрытия:

- [x] контейнеры не работают от root без необходимости
- [x] базовые эксплуатационные guardrails настроены

### P1-05. Расширить test coverage

- [x] Добавить integration tests для ClickHouse migrations
- [x] Добавить integration tests для `sys_watermarks`
- [x] Добавить integration tests для Redis locks
- [x] Добавить integration tests для transforms correctness
- [x] Добавить integration tests для marts correctness
- [x] Добавить tests на admin whitelist
- [x] Добавить e2e smoke flow `bootstrap -> ingest -> transform -> marts -> api`
- [x] Добавить coverage для Ozon/WB edge payload variants

Критерии закрытия:

- [x] ключевые data paths покрыты не только unit tests
- [x] есть smoke test для всей цепочки

### P1-06. Ввести data quality checks

- [x] Проверять stale `mrt_*`
- [x] Проверять monotonicity watermark
- [x] Проверять duplicate keys на ожидаемом grain
- [x] Проверять impossible timestamps
- [x] Проверять отрицательные/аномальные значения, где это недопустимо
- [x] Добавить scheduled quality task
- [x] Логировать quality failures в понятный audit trail

Критерии закрытия:

- [x] silent data corruption выявляется автоматически
- [x] quality failures видны в monitoring и task logs

### P1-07. Усилить API contract и query safety

- [x] Добавить более строгую валидацию query params
- [x] Ограничить max date windows для тяжелых endpoint'ов
- [x] Рассмотреть pagination вместо простого `limit`
- [x] Добавить стандартную error model для API
- [x] Явно типизировать dependency-injected clients в endpoints
- [x] Санитизировать internal errors в response payload

Критерии закрытия:

- [x] API ведет себя предсказуемо при некорректных входных параметрах
- [x] тяжелые запросы нельзя вызвать без ограничений

### P1-08. Скрыть внутренние детали в readiness/errors

- [x] Убрать raw exception text из `/ready`
- [x] Убрать лишние инфраструктурные детали из admin error responses
- [x] Перенести детальные причины в structured logs
- [x] Проверить, что troubleshooting не страдает после sanitization

Критерии закрытия:

- [x] public responses не раскрывают внутреннюю топологию и stack details

### P1-09. Кэшировать SQL templates

- [x] Кэшировать SQL-файлы в `MetricsService`
- [x] Кэшировать SQL-файлы в `AdminService`
- [x] Проверить поведение на hot reload/dev режиме
- [x] Добавить тест или profiling note на отсутствие лишнего file IO

Критерии закрытия:

- [x] SQL templates не читаются с диска на каждый запрос

### P1-10. Обновить docs и runbooks

- [x] Обновить [README.md](/home/borm/VibeCoding/BormoStats/marketplace-analytics/README.md)
- [x] Обновить [troubleshooting.md](/home/borm/VibeCoding/BormoStats/marketplace-analytics/docs/troubleshooting.md)
- [x] Добавить runbook по stalled watermark
- [x] Добавить runbook по Redis issues
- [x] Добавить runbook по ClickHouse storage pressure
- [x] Добавить runbook по upstream 429/5xx
- [x] Добавить release checklist в docs

Критерии закрытия:

- [x] оператор может восстановить систему по документации без знания автора

## Phase P2: Production Platform Maturity

### P2-01. Reverse proxy, TLS, network segmentation

- [x] Реализовать nginx/reverse proxy слой
- [x] Настроить TLS termination
- [x] Добавить security headers
- [x] Изолировать internal services в private network
- [x] Ограничить внешний доступ к ClickHouse/Redis/worker endpoints

### P2-02. Разделить окружения

- [x] Описать `dev/stage/prod` env model
- [x] Развести secrets по окружениям
- [x] Развести stack names и published ports
- [x] Настроить promotion flow между stage и prod

### P2-03. Backup and disaster recovery

- [x] Определить backup strategy для ClickHouse
- [x] Определить backup strategy для Metabase
- [x] Описать backup strategy для env/secrets
- [x] Провести restore drill на чистом окружении
- [x] Задокументировать RPO/RTO

### P2-04. Supply-chain security

- [ ] Добавить dependency vulnerability scan
- [ ] Добавить container image scan
- [ ] Сформировать SBOM
- [ ] Описать policy обновления зависимостей и образов

### P2-05. Performance and load validation

- [ ] Определить target throughput по ingestion
- [ ] Определить target latency по API
- [ ] Провести нагрузочный тест backend
- [ ] Провести нагрузочный тест transforms/marts
- [ ] Зафиксировать безопасные concurrency limits

### P2-06. Release management

- [ ] Ввести versioning policy
- [ ] Ввести release notes template
- [ ] Описать rollback procedure
- [ ] Описать production deploy checklist

### P2-07. Security review и rotation

- [ ] Описать ротацию marketplace tokens
- [ ] Описать ротацию admin/API keys
- [ ] Описать ротацию ClickHouse/Redis credentials
- [ ] Провести least-privilege review

### P2-08. Дисциплина миграций

- [ ] Зафиксировать forward-only migration policy
- [ ] Описать dry-run validation для schema changes
- [ ] Описать rollback/mitigation strategy для неудачной миграции
- [ ] Добавить migration review checklist

## Global Verification Checklist

- [ ] `ruff check .`
- [ ] `black --check .`
- [ ] `mypy backend workers collectors automation warehouse scripts`
- [ ] `pytest -q`
- [ ] GitHub Actions green
- [ ] Docker bootstrap проходит на чистой машине
- [ ] Migrations проходят на чистой базе
- [ ] Worker, beat, backend метрики доступны
- [ ] Alerts настроены и протестированы
- [ ] Backup/restore проверены
- [ ] Release checklist выполнен

## Suggested Execution Order

- [ ] Sprint 1: `P0-01`, `P0-02`, `P0-04`, `P0-05`, `P0-09`
- [ ] Sprint 2: `P0-06`, `P0-07`, `P0-08`, `P0-10`
- [ ] Sprint 3: `P1-01`, `P1-03`, `P1-04`, `P1-05`, `P1-08`
- [ ] Sprint 4: `P1-06`, `P1-07`, `P1-10`, `P2-03`
