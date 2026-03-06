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

- [ ] Закрыть все текущие `ruff` ошибки
- [ ] Закрыть все текущие `black --check` расхождения
- [ ] Закрыть все текущие `mypy` ошибки
- [ ] Устранить import-path проблемы в mypy для `backend/app` и `workers/app`
- [ ] Устранить untyped decorator issues вокруг Celery tasks
- [ ] Добавить missing type stubs или правильные mypy overrides
- [ ] Прогнать `pytest` на чистом окружении
- [ ] Убедиться, что CI workflow повторяет локальные quality gates

Критерии закрытия:

- [ ] `ruff check .` зеленый
- [ ] `black --check .` зеленый
- [ ] `mypy backend workers collectors automation warehouse scripts` зеленый
- [ ] `pytest -q` зеленый
- [ ] GitHub Actions workflow зеленый

### P0-09. Починить migration smoke workflow

- [ ] Исправить host/port assumptions в [ci.yml](/home/borm/VibeCoding/BormoStats/.github/workflows/ci.yml)
- [ ] Убедиться, что `.env.example` не ломает GitHub runner networking
- [ ] Исправить bootstrap переменные для CI ClickHouse endpoint
- [ ] Проверить `apply_migrations.py` в CI runtime
- [ ] Добавить явную проверку ключевых таблиц после migrations
- [ ] Проверить cleanup docker services в `always()`

Критерии закрытия:

- [ ] migration smoke job стабильно проходит на GitHub Actions
- [ ] migrations реально применяются, а не падают на неверном host/port

### P0-10. Пиновать зависимости и образы

- [ ] Зафиксировать версии Python dependencies в [requirements.txt](/home/borm/VibeCoding/BormoStats/marketplace-analytics/requirements.txt)
- [ ] Зафиксировать версии dev dependencies
- [ ] Пиновать Docker base images в [backend/Dockerfile](/home/borm/VibeCoding/BormoStats/marketplace-analytics/backend/Dockerfile)
- [ ] Пиновать Docker base images в [workers/Dockerfile](/home/borm/VibeCoding/BormoStats/marketplace-analytics/workers/Dockerfile)
- [ ] Заменить `latest` на фиксированные версии в [docker-compose.yml](/home/borm/VibeCoding/BormoStats/marketplace-analytics/infra/docker/docker-compose.yml)
- [ ] Зафиксировать policy обновления зависимостей в docs

Критерии закрытия:

- [ ] docker images reproducible
- [ ] Python environment reproducible
- [ ] redeploy не меняет behavior без изменения кода

## Phase P1: Operational Hardening

### P1-01. Экспортировать worker и beat metrics

- [ ] Выбрать модель экспорта: отдельный endpoint или sidecar exporter
- [ ] Поднять metrics endpoint для worker
- [ ] Поднять metrics endpoint для beat
- [ ] Добавить scrape config/документацию для Prometheus
- [ ] Проверить экспорт `task_duration_seconds`
- [ ] Проверить экспорт `task_runs_total`
- [ ] Проверить экспорт `watermark_lag_seconds`
- [ ] Проверить экспорт `empty_payload_total`

Критерии закрытия:

- [ ] метрики worker и beat доступны снаружи
- [ ] operational dashboards могут их читать

### P1-02. Настроить alerting и dashboards

- [ ] Определить alert rules для failed task runs
- [ ] Определить alert rules для stale watermarks
- [ ] Определить alert rules для empty payload anomalies
- [ ] Определить alert rules для Redis saturation
- [ ] Определить alert rules для ClickHouse disk / readiness
- [ ] Подготовить базовый operational dashboard
- [ ] Подготовить dashboard по ingestion freshness

Критерии закрытия:

- [ ] alerts описаны, настроены и тестово срабатывают
- [ ] есть dashboard для ежедневной эксплуатации

### P1-03. Ограничить рост Redis/Celery metadata

- [ ] Решить, нужны ли task results вообще
- [ ] Если не нужны, включить `task_ignore_result = true`
- [ ] Если нужны, добавить expiry/retention policy
- [ ] Проверить поведение admin workflows после изменения
- [ ] Обновить docs по Redis retention

Критерии закрытия:

- [ ] Redis не накапливает бесконечно task metadata
- [ ] admin/API flow не ломается после изменения result policy

### P1-04. Harden Docker runtime

- [ ] Перевести backend container на non-root user
- [ ] Перевести worker container на non-root user
- [ ] Добавить `restart` policies в compose
- [ ] Добавить resource limits / reservations
- [ ] Добавить/уточнить healthchecks для backend, worker, beat
- [ ] Рассмотреть read-only filesystem где возможно
- [ ] Обновить docs по runtime assumptions

Критерии закрытия:

- [ ] контейнеры не работают от root без необходимости
- [ ] базовые эксплуатационные guardrails настроены

### P1-05. Расширить test coverage

- [ ] Добавить integration tests для ClickHouse migrations
- [ ] Добавить integration tests для `sys_watermarks`
- [ ] Добавить integration tests для Redis locks
- [ ] Добавить integration tests для transforms correctness
- [ ] Добавить integration tests для marts correctness
- [ ] Добавить tests на admin whitelist
- [ ] Добавить e2e smoke flow `bootstrap -> ingest -> transform -> marts -> api`
- [ ] Добавить coverage для Ozon/WB edge payload variants

Критерии закрытия:

- [ ] ключевые data paths покрыты не только unit tests
- [ ] есть smoke test для всей цепочки

### P1-06. Ввести data quality checks

- [ ] Проверять stale `mrt_*`
- [ ] Проверять monotonicity watermark
- [ ] Проверять duplicate keys на ожидаемом grain
- [ ] Проверять impossible timestamps
- [ ] Проверять отрицательные/аномальные значения, где это недопустимо
- [ ] Добавить scheduled quality task
- [ ] Логировать quality failures в понятный audit trail

Критерии закрытия:

- [ ] silent data corruption выявляется автоматически
- [ ] quality failures видны в monitoring и task logs

### P1-07. Усилить API contract и query safety

- [ ] Добавить более строгую валидацию query params
- [ ] Ограничить max date windows для тяжелых endpoint'ов
- [ ] Рассмотреть pagination вместо простого `limit`
- [ ] Добавить стандартную error model для API
- [ ] Явно типизировать dependency-injected clients в endpoints
- [ ] Санитизировать internal errors в response payload

Критерии закрытия:

- [ ] API ведет себя предсказуемо при некорректных входных параметрах
- [ ] тяжелые запросы нельзя вызвать без ограничений

### P1-08. Скрыть внутренние детали в readiness/errors

- [ ] Убрать raw exception text из `/ready`
- [ ] Убрать лишние инфраструктурные детали из admin error responses
- [ ] Перенести детальные причины в structured logs
- [ ] Проверить, что troubleshooting не страдает после sanitization

Критерии закрытия:

- [ ] public responses не раскрывают внутреннюю топологию и stack details

### P1-09. Кэшировать SQL templates

- [ ] Кэшировать SQL-файлы в `MetricsService`
- [ ] Кэшировать SQL-файлы в `AdminService`
- [ ] Проверить поведение на hot reload/dev режиме
- [ ] Добавить тест или profiling note на отсутствие лишнего file IO

Критерии закрытия:

- [ ] SQL templates не читаются с диска на каждый запрос

### P1-10. Обновить docs и runbooks

- [ ] Обновить [README.md](/home/borm/VibeCoding/BormoStats/marketplace-analytics/README.md)
- [ ] Обновить [troubleshooting.md](/home/borm/VibeCoding/BormoStats/marketplace-analytics/docs/troubleshooting.md)
- [ ] Добавить runbook по stalled watermark
- [ ] Добавить runbook по Redis issues
- [ ] Добавить runbook по ClickHouse storage pressure
- [ ] Добавить runbook по upstream 429/5xx
- [ ] Добавить release checklist в docs

Критерии закрытия:

- [ ] оператор может восстановить систему по документации без знания автора

## Phase P2: Production Platform Maturity

### P2-01. Reverse proxy, TLS, network segmentation

- [ ] Реализовать nginx/reverse proxy слой
- [ ] Настроить TLS termination
- [ ] Добавить security headers
- [ ] Изолировать internal services в private network
- [ ] Ограничить внешний доступ к ClickHouse/Redis/worker endpoints

### P2-02. Разделить окружения

- [ ] Описать `dev/stage/prod` env model
- [ ] Развести secrets по окружениям
- [ ] Развести stack names и published ports
- [ ] Настроить promotion flow между stage и prod

### P2-03. Backup and disaster recovery

- [ ] Определить backup strategy для ClickHouse
- [ ] Определить backup strategy для Metabase
- [ ] Описать backup strategy для env/secrets
- [ ] Провести restore drill на чистом окружении
- [ ] Задокументировать RPO/RTO

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
