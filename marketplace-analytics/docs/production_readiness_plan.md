# Production Readiness Plan

Дата составления: 2026-03-06

## Цель

Этот документ переводит результаты аудита в исполнимый план работ.
Под "100% production ready" в рамках этого проекта понимается практическое состояние, при котором:

- нет известных `Critical` и `High` дефектов, способных привести к компрометации, потере данных или неконтролируемому простою;
- сборка, тесты, миграции и деплой воспроизводимы и проходят автоматически;
- ingestion, transforms, marts и admin flow наблюдаемы, ограничены и безопасны;
- восстановление после сбоя проверено на практике, а не только описано в документации.

## Текущий статус по итогам аудита

| Область | Текущее состояние | Риск |
| --- | --- | --- |
| Secrets и доступ | В коде и шаблонах есть публично известные дефолты (`change_me`, `admin_password`) | Critical |
| Admin plane | `/admin/run-task` позволяет отправлять произвольные Celery tasks | Critical |
| Retry и circuit breaker | Повторяются non-retryable ошибки и даже `CircuitOpenError` | Critical |
| Data correctness | Некорректно парсится `canceled_at` у Ozon postings | High |
| Concurrency control | Нет продления lock TTL, нет serialization для rebuild tasks | High |
| CI / quality gates | `ruff` и `mypy` падают, migration smoke workflow рассинхронизирован | High |
| Build reproducibility | Используются `latest` и непинованные Python зависимости | High |
| Observability | Worker метрики не экспортируются наружу | Medium |
| Infra hardening | Контейнеры запускаются без non-root, restart policy, resource limits | Medium |
| Test coverage | Есть unit tests, но почти нет integration/e2e/data-quality сценариев | Medium |

## Критерии готовности к production

- `ruff`, `black --check`, `mypy`, `pytest` зеленые локально и в CI.
- Docker images и Python зависимости pinned.
- Нет insecure defaults в коде, `.env.example` и init SQL.
- Admin endpoints доступны только при явной и безопасной конфигурации.
- Collector tasks, transforms и marts не гоняются параллельно конфликтующим образом.
- Поведение watermark и locks детерминировано, проверено автотестами.
- Есть метрики, dashboards и alerting для backend, worker, beat, ClickHouse, Redis.
- Есть backup/restore сценарий и проверенный recovery drill.
- Есть release checklist и runbooks для инцидентов.

## Стратегия исполнения

- Сначала закрываются `P0` задачи. До их завершения проект не считать готовым к внешнему доступу.
- После `P0` закрываются `P1` задачи, которые доводят эксплуатационную зрелость до production baseline.
- `P2` задачи доводят систему до устойчивого long-term operation и масштабирования.
- Каждая фаза завершается отдельным freeze: code review, quality gates, smoke tests, regression tests, обновление документации.

## Phase P0: Security, Correctness, Release Blockers

Цель фазы: убрать прямые риски компрометации, silent data corruption и поломанный release pipeline.

| ID | Задача | Основные области | Результат | Acceptance criteria |
| --- | --- | --- | --- | --- |
| P0-01 | Убрать insecure defaults и fail-fast на placeholder values | `backend/app/core/config.py`, `.env.example`, `infra/docker/clickhouse/initdb/001_users.sql`, bootstrap scripts | Нет секретов и "рабочих" дефолтов в репозитории | backend не стартует с `ADMIN_API_KEY=change_me`; ClickHouse admin password не зашит в git; bootstrap требует явных credentials |
| P0-02 | Сузить admin control plane | `backend/app/api/v1/admin.py`, `backend/app/services/admin_service.py`, UI admin flow | Вместо arbitrary `run-task` остается whitelist допустимых admin operations | нет API для произвольного `task_name`; все admin команды типизированы и валидируются |
| P0-03 | Убрать хранение admin key в `localStorage` | `backend/app/ui/app.js`, UI docs | Секрет не персистится в браузере | ключ живет только in-memory/session scope; documented behavior |
| P0-04 | Исправить retry semantics и circuit breaker | `collectors/common/http_client.py`, tests | Повторяются только retryable ошибки | `429` и `5xx` retry; `400/401/403` fail-fast; `CircuitOpenError` не уходит в retry loop; покрыто unit tests |
| P0-05 | Исправить Ozon `canceled_at` parsing | `collectors/ozon/parsers.py`, parser tests | Cancellation timestamp сохраняется корректно | тест на cancelled posting проходит; historical sample data не пишет `cancel_reason_id` в `canceled_at` |
| P0-06 | Сериализовать destructive rebuild tasks | `workers/app/tasks/transforms.py`, `workers/app/tasks/marts.py`, lock utils, beat schedule | `transform` и `marts` не конфликтуют и исполняются в правильном порядке | Redis lock на rebuild jobs; нет параллельных конфликтующих delete/insert; есть integration test |
| P0-07 | Сделать locks продлеваемыми или безопасно долгоживущими | `workers/app/utils/locking.py`, collector tasks | Long-running jobs не теряют эксклюзивность | lock renew/heartbeat реализован; backfill не может самопересекаться после истечения TTL |
| P0-08 | Починить CI до полностью зеленого состояния | `.github/workflows/ci.yml`, `pyproject.toml`, typing/lint issues по проекту | CI становится release gate, а не формальностью | `ruff`, `black --check`, `mypy`, `pytest`, migration smoke проходят на чистом runner |
| P0-09 | Исправить migration smoke workflow | `.github/workflows/ci.yml`, `.env.example`, bootstrap assumptions | CI реально проверяет migrations, а не падает из-за неверного host/port | workflow стартует ClickHouse/Redis и успешно применяет migrations на GitHub Actions |
| P0-10 | Пиновать образы и Python зависимости | `requirements.txt`, Dockerfiles, compose | Сборка воспроизводима | exact versions для Python deps; Docker image tags pinned до fixed version/digest |

### Детализация P0

#### P0-01. Secrets и default credentials

- Удалить рабочие значения из `.env.example`.
- Заменить `ADMIN_API_KEY=change_me` на отсутствие дефолта и жесткую валидацию при старте.
- Убрать `CREATE USER admin ... BY 'admin_password'` из init SQL.
- Вынести provisioning privileged users в безопасный bootstrap path или внешнюю secret-management схему.
- Добавить startup check, который логирует и останавливает backend/worker при placeholder credentials.

#### P0-02. Безопасный admin plane

- Удалить или скрыть `/api/v1/admin/run-task`.
- Оставить только whitelist: backfill, transform rebuild, marts rebuild, maintenance jobs.
- Для каждой admin операции определить отдельную Pydantic-модель запроса.
- Ограничить максимальные `days`, допустимые marketplace/dataset values и concurrency.
- Добавить audit logging: кто, когда, откуда, что запустил.

#### P0-04. Retry и circuit breaker

- Разделить retryable и non-retryable исключения.
- Обрабатывать `httpx.HTTPStatusError` по status code, а не общим блоком.
- Исключить retry на `CircuitOpenError`.
- В логах явно различать upstream throttling, client error и local transport failure.
- Добавить tests на `429`, `500`, `400`, `403`, circuit-open path.

#### P0-06. Serialization для transforms и marts

- Добавить отдельные lock keys: `transform_all_recent`, `transform_backfill`, `build_marts_recent`, `build_marts_backfill`.
- Запретить одновременный запуск destructive rebuild jobs.
- Перевести расписание на явную последовательность: `collectors -> transform -> marts`.
- Добавить signalization в `sys_task_runs` и Prometheus при skipped/conflicting runs.

## Phase P1: Operational Hardening

Цель фазы: довести систему до эксплуатационной зрелости production baseline.

| ID | Задача | Основные области | Результат | Acceptance criteria |
| --- | --- | --- | --- | --- |
| P1-01 | Экспортировать worker и beat metrics | worker runtime, metrics bootstrap, infra | Worker метрики скрапятся Prometheus | отдельный metrics endpoint или sidecar; видны task duration, rows, watermark lag, empty payload |
| P1-02 | Настроить alerting и dashboards | backend metrics, worker metrics, ClickHouse, Redis | Есть operational visibility | alerts на task failures, watermark lag, Redis memory, ClickHouse disk, backend readiness |
| P1-03 | Ограничить рост Redis/Celery metadata | `workers/app/celery_app.py`, Redis config | Redis не переполняется task result metadata | либо `task_ignore_result = true`, либо TTL/results expiry; documented retention |
| P1-04 | Harden Docker runtime | compose, Dockerfiles | Контейнеры запускаются безопаснее и устойчивее | non-root users, `restart: unless-stopped`, healthchecks, memory/cpu limits, read-only fs where possible |
| P1-05 | Расширить test coverage | tests, CI | Покрыты реальные failure modes | integration tests на ClickHouse + Redis; e2e smoke tests на API; regression tests для watermark/locks |
| P1-06 | Ввести data quality checks | warehouse, transforms, maintenance | Silent data corruption выявляется автоматически | checks на nullability, duplicate keys, stale marts, impossible timestamps, negative values |
| P1-07 | Усилить API contract и query safety | backend API, service layer | API предсказуем и безопасен под нагрузкой | stricter validation, pagination, sensible defaults, max window limits, standardized error model |
| P1-08 | Скрыть внутренние детали в readiness/errors | backend | Публичное API не раскрывает topology/internal exceptions | `/ready` и admin errors не утекут с raw exception text |
| P1-09 | Кэшировать SQL templates и снизить runtime overhead | backend services | Меньше лишнего IO и проще profiling | SQL читается один раз на process start или кешируется |
| P1-10 | Стабилизировать docs и runbooks | `README.md`, `docs/` | Операционная документация соответствует коду | quickstart, troubleshooting, rollback, backup/restore актуальны |

### Детализация P1

#### P1-01. Наблюдаемость

- Добавить отдельный экспорт метрик из worker и beat.
- Добавить бизнес-метрики: rows per source, task lag, stale watermark age, last successful run per source.
- Добавить correlation IDs между API request, task launch и `sys_task_runs`.
- Подготовить базовые Grafana/Metabase operational dashboards.

#### P1-05. Test strategy

- Unit tests оставить как baseline.
- Добавить integration tests:
  - `watermark set/get monotonicity`;
  - Redis lock acquire/renew/release;
  - transform rebuild correctness на маленьком фикстурном наборе;
  - marts rebuild correctness;
  - admin backfill whitelist enforcement.
- Добавить e2e smoke:
  - bootstrap stack;
  - apply migrations;
  - ingest fixture data;
  - build marts;
  - read backend endpoints.

#### P1-06. Data quality checks

- Проверять, что `mrt_*` не старее ожидаемого окна.
- Проверять, что `sys_watermarks` растут монотонно.
- Проверять отсутствие аномально больших скачков row count и пустых payload bursts.
- Проверять уникальность ключей по expected grain для `raw`, `stg`, `mrt`.

## Phase P2: Production Platform Maturity

Цель фазы: обеспечить долгосрочную эксплуатацию, масштабирование и безопасный внешний доступ.

| ID | Задача | Основные области | Результат | Acceptance criteria |
| --- | --- | --- | --- | --- |
| P2-01 | Добавить reverse proxy, TLS и network segmentation | `infra/docker/nginx`, deploy topology | Сервис готов к внешнему доступу | TLS termination, security headers, private network for internal services |
| P2-02 | Разделить окружения | CI/CD, env management | `dev`, `stage`, `prod` живут независимо | разные env/secrets/stacks, promotion pipeline, no shared credentials |
| P2-03 | Backup and disaster recovery | ClickHouse, Metabase, env/secrets | Восстановление после сбоя проверено | documented backup policy, restore drill, RPO/RTO targets met |
| P2-04 | Supply-chain security | Docker, Python deps, CI | Release pipeline контролирует уязвимости | SBOM, vulnerability scan, dependency update policy |
| P2-05 | Performance and load validation | API, ClickHouse, collectors | Система выдерживает целевую нагрузку | documented throughput, latency budgets, tested concurrency ceiling |
| P2-06 | Controlled release management | release checklist, tagging, changelog | Выкатки предсказуемы и откатываемы | semantic versioning, release notes, rollback playbook |
| P2-07 | Security review and secrets rotation | admin/API/infra | Секреты и доступы управляются как в зрелой production системе | rotation cadence, least privilege, audit trail |
| P2-08 | Long-term schema migration discipline | warehouse migrations | Схема эволюционирует безопасно | forward-only migration policy, dry-run validation, rollback strategy |

## Очередность внедрения

### Sprint 1

- P0-01 Secrets и default credentials
- P0-02 Admin whitelist
- P0-04 Retry semantics
- P0-05 Ozon `canceled_at`
- P0-09 CI migration smoke fix

### Sprint 2

- P0-06 Serialization для transforms/marts
- P0-07 Renewable locks
- P0-08 Full green CI
- P0-10 Pinned dependencies and images

### Sprint 3

- P1-01 Worker metrics export
- P1-03 Redis/Celery retention
- P1-04 Docker hardening
- P1-05 Integration and e2e tests
- P1-08 Error sanitization

### Sprint 4

- P1-06 Data quality checks
- P1-07 API contract hardening
- P1-10 Runbooks and docs
- P2-03 Backup/restore

## Release checklist перед production launch

- Все `P0` и `P1` задачи закрыты.
- `main` green в CI не менее 5 последовательных прогонов.
- Публичных дефолтных секретов в repo нет.
- Docker images pinned и пересобираемы.
- Проверен bootstrap на чистой машине.
- Проверен recovery после:
  - падения backend;
  - падения worker;
  - падения Redis;
  - падения ClickHouse;
  - потери сети к маркетплейсу;
  - истечения/ротации API токенов.
- Есть dashboards и alerts.
- Есть runbook для backfill, stalled watermark, Redis saturation, ClickHouse storage pressure, upstream 429/5xx.
- Проведен smoke test на staging после последней миграции.

## Что считать завершением проекта

Проект можно считать production-ready только после выполнения всех условий:

- нет открытых `Critical` и `High` рисков;
- quality gates встроены в release process и реально блокируют merge/release;
- runtime, infra и recovery сценарии проверены на практике;
- эксплуатация не зависит от ручного знания автора проекта.

## Рекомендуемый следующий шаг

Начать с отдельного execution batch по `P0-01`, `P0-02`, `P0-04`, `P0-05`, `P0-09`.
Это самый короткий путь от текущего состояния к безопасной и предсказуемой базе для последующей hardening-фазы.
