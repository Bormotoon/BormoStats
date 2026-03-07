# BormoStats — Аналитика маркетплейсов (Wildberries + Ozon)

Самостоятельно размещаемая (self-hosted) аналитическая платформа для продавцов на Wildberries и Ozon. Система автоматически собирает данные из API маркетплейсов, строит аналитические витрины и предоставляет готовые дашборды, REST API и Telegram-уведомления — всё на собственной инфраструктуре без передачи данных третьим сторонам.

---

## Содержание

- [Обзор проекта](#обзор-проекта)
- [Архитектура](#архитектура)
  - [Общая схема](#общая-схема)
  - [Компоненты](#компоненты)
  - [Слои данных](#слои-данных)
- [Технологический стек](#технологический-стек)
- [Структура репозитория](#структура-репозитория)
- [Быстрый старт](#быстрый-старт)
  - [Предварительные требования](#предварительные-требования)
  - [Установка и запуск](#установка-и-запуск)
  - [Проверка здоровья](#проверка-здоровья)
- [Конфигурация](#конфигурация)
  - [Обязательные переменные окружения](#обязательные-переменные-окружения)
  - [Опциональные переменные](#опциональные-переменные)
  - [Порты по умолчанию](#порты-по-умолчанию)
- [Веб-интерфейс](#веб-интерфейс)
- [API](#api)
  - [Публичные эндпоинты аналитики](#публичные-эндпоинты-аналитики)
  - [Административные эндпоинты](#административные-эндпоинты)
- [Сбор данных](#сбор-данных)
  - [Wildberries](#wildberries)
  - [Ozon](#ozon)
  - [Расписание задач](#расписание-задач)
- [Хранилище данных (ClickHouse)](#хранилище-данных-clickhouse)
  - [Миграции](#миграции)
  - [Raw-слой](#raw-слой)
  - [Staging-слой](#staging-слой)
  - [Мартовый слой](#мартовый-слой)
  - [Системные таблицы](#системные-таблицы)
- [Автоматизация и уведомления](#автоматизация-и-уведомления)
- [Дашборды](#дашборды)
- [Мониторинг и наблюдаемость](#мониторинг-и-наблюдаемость)
- [Безопасность](#безопасность)
- [Среды (dev / stage / prod)](#среды-dev--stage--prod)
- [CI/CD](#cicd)
- [Тестирование](#тестирование)
- [Полезные команды](#полезные-команды)
- [Устранение неполадок](#устранение-неполадок)
- [Резервное копирование и восстановление](#резервное-копирование-и-восстановление)
- [Разработка и Contributing](#разработка-и-contributing)
- [Документация](#документация)
- [Лицензия](#лицензия)

---

## Обзор проекта

BormoStats — это production-ready аналитическая система, спроектированная для владельцев магазинов на Wildberries и Ozon. Система работает **исключительно с данными собственных продавческих кабинетов** — не собирает информацию о конкурентах и не скрейпит витрины маркетплейсов.

### Что умеет BormoStats

| Функция | Описание |
|---|---|
| **Автосбор данных** | Инкрементальный сбор продаж, заказов, остатков, воронки, рекламы и финансов из WB/Ozon API |
| **Аналитическое хранилище** | Трёхслойный data warehouse в ClickHouse (raw → staging → marts) |
| **REST API** | FastAPI-бэкенд с эндпоинтами для продаж, остатков, воронки, рекламы и KPI |
| **Веб-интерфейс** | Встроенный Material 3 UI с дашбордом и страницами по доменам |
| **BI-дашборды** | Интеграция с Metabase для произвольных дашбордов и SQL-запросов |
| **Telegram-алерты** | YAML-правила автоматизации: высокий ACOS, низкие остатки, нет продаж |
| **Администрирование** | Admin API для бэкфиллов, трансформов, водяных знаков и аудита задач |
| **Мониторинг** | Prometheus-метрики, Grafana-дашборды, алерт-правила |

### Границы проекта

- ✅ Данные **только** из собственных продавческих кабинетов WB и Ozon
- ✅ Локальное/self-hosted развёртывание
- ❌ Не собирает данные конкурентов или рыночную аналитику
- ❌ Не скрейпит витрины маркетплейсов

---

## Архитектура

### Общая схема

```
┌──────────────────────────────────────────────────────────────────┐
│                       CELERY BEAT (Планировщик)                  │
│       Запускает сборщики, трансформы, мартовые сборки,           │
│       автоматизацию и обслуживание по расписанию                 │
└────────────┬─────────────────┬──────────────────┬────────────────┘
             │                 │                  │
             ▼                 ▼                  ▼
┌────────────────┐  ┌──────────────────┐  ┌────────────────────────┐
│  WB Collector  │  │  Ozon Collector  │  │  Transforms & Marts    │
│  (API клиент)  │  │  (API клиент)    │  │  (SQL-трансформации)   │
└───────┬────────┘  └────────┬─────────┘  └───────────┬────────────┘
        │                    │                        │
        ▼                    ▼                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                    CLICKHOUSE (Хранилище)                         │
│  raw_* → stg_* → mrt_*   |   sys_watermarks   |   sys_task_runs │
└────────────┬─────────────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────┐
│           FastAPI Backend                       │
│  /api/v1/* (аналитика) + /api/v1/admin/* (адм)│
│  /ui (веб-интерфейс) + /metrics (Prometheus)  │
└────────────┬───────────────────────────────────┘
             │
             ▼
┌────────────────────────────────┐  ┌────────────────┐
│  Nginx Reverse Proxy (TLS)    │  │    Metabase     │
│  → публичная точка входа      │  │  (BI дашборды)  │
└───────────────────────────────┘  └────────────────┘
```

### Компоненты

| Компонент | Технология | Назначение |
|---|---|---|
| **Backend** | FastAPI + Uvicorn | REST API, веб-UI, health/ready/metrics |
| **Worker** | Celery | Сбор данных, трансформы, мартовые сборки, обслуживание |
| **Beat** | Celery Beat | Планировщик периодических задач |
| **ClickHouse** | ClickHouse | Аналитическое OLAP-хранилище |
| **Redis** | Redis | Брокер задач Celery + распределённые блокировки |
| **Nginx** | Nginx | Обратный прокси с TLS |
| **Metabase** | Metabase | BI-платформа для дашбордов |
| **Prometheus** | Prometheus | Сбор и хранение метрик |

### Слои данных

Данные проходят через три уровня обработки:

1. **Raw-слой** (`raw_*`) — сырые данные из API маркетплейсов с JSON-полезной нагрузкой и нормализованными ключевыми полями для идемпотентной загрузки
2. **Staging-слой** (`stg_*`) — каноническая нормализованная модель с единой схемой для WB и Ozon
3. **Mart-слой** (`mrt_*`) — агрегированные BI-витрины, готовые для дашбордов и API

---

## Технологический стек

| Категория | Технологии |
|---|---|
| **Язык** | Python 3.12 |
| **Веб-фреймворк** | FastAPI 0.135, Uvicorn 0.41 |
| **Задачи** | Celery 5.6, Redis 7.2 |
| **Хранилище** | ClickHouse (clickhouse-connect 0.13) |
| **HTTP-клиент** | httpx 0.28 |
| **Валидация** | Pydantic 2.12, pydantic-settings 2.13 |
| **Метрики** | prometheus_client 0.24 |
| **Логирование** | structlog 25.5 (структурированный JSON) |
| **Автоматизация** | PyYAML 6.0 (YAML-правила) |
| **BI** | Metabase (Docker) |
| **Инфраструктура** | Docker Compose, Nginx, Prometheus, Grafana |
| **Линтеры** | Ruff 0.15, Black 26.1 |
| **Типизация** | MyPy 1.19 (strict mode) |
| **Тесты** | pytest 9.0, pytest-asyncio |
| **Безопасность** | pip-audit, Anchore Grype (Docker-сканы), SBOM-генерация |

---

## Структура репозитория

```
BormoStats/
├── .github/                    # CI/CD, шаблоны issue/PR, Dependabot
│   ├── workflows/ci.yml        # GitHub Actions pipeline
│   ├── ISSUE_TEMPLATE/         # Шаблоны создания issues
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml          # Автообновление зависимостей
│
├── marketplace-analytics/      # Основной пакет приложения
│   ├── automation/             # Движок правил автоматизации
│   │   ├── engine.py           # Безопасный вычислитель YAML-правил (AST)
│   │   ├── actions/            # Исполнители действий
│   │   │   ├── base.py         # Базовый класс действий
│   │   │   └── telegram.py     # Отправка Telegram-уведомлений
│   │   └── rules/              # YAML-правила
│   │       ├── bad_acos.yml    # ACOS > 30%
│   │       ├── low_stock.yml   # Низкие остатки
│   │       └── no_sales_7d.yml # Нет продаж 7 дней
│   │
│   ├── backend/                # FastAPI бэкенд
│   │   ├── Dockerfile
│   │   └── app/
│   │       ├── main.py         # Точка входа: роутеры, здоровье, метрики
│   │       ├── api/            # REST API роутеры
│   │       │   └── v1/         # sales, stocks, funnel, ads, kpis, admin
│   │       ├── core/           # Конфигурация, зависимости
│   │       ├── db/             # ClickHouse-клиент, SQL-запросы
│   │       ├── models/         # Pydantic-модели запросов/ответов
│   │       ├── services/       # Бизнес-логика (MetricsService, AdminService)
│   │       └── ui/             # Встроенный веб-интерфейс (Material 3)
│   │
│   ├── collectors/             # Клиенты API маркетплейсов
│   │   ├── common/             # Общая инфраструктура
│   │   │   ├── http_client.py  # HTTP-клиент с retry, circuit breaker, редакцией
│   │   │   ├── retry.py        # Стратегии повтора (backoff, jitter, WB-специфика)
│   │   │   ├── redaction.py    # Маскирование чувствительных данных в логах
│   │   │   └── time.py         # Утилиты работы со временем
│   │   ├── wb/                 # Wildberries API клиент
│   │   │   ├── client.py       # WbApiClient: sales, orders, stocks, funnel
│   │   │   ├── endpoints.py    # URL-эндпоинты WB API
│   │   │   └── parsers.py      # Парсинг и нормализация ответов WB
│   │   └── ozon/               # Ozon API клиент
│   │       ├── client.py       # OzonApiClient: postings, stocks, ads, finance
│   │       ├── endpoints.py    # URL-эндпоинты Ozon API
│   │       ├── errors.py       # Обработка ошибок Ozon
│   │       └── parsers.py      # Парсинг и нормализация ответов Ozon
│   │
│   ├── common/                 # Общие утилиты
│   │   ├── celery_config.py    # Конфигурация Celery: очереди, маршрутизация
│   │   └── env_validation.py   # Валидация переменных окружения
│   │
│   ├── dashboards/             # SQL-дашборды и Grafana
│   │   ├── manifest.yml        # Манифест обязательных дашбордов
│   │   ├── grafana/            # JSON-модели Grafana
│   │   │   ├── operational_overview.json
│   │   │   └── ingestion_freshness.json
│   │   └── sql/                # SQL для аналитических дашбордов
│   │       ├── 01_sales_overview.sql
│   │       ├── 02_top_products_30d.sql
│   │       ├── 03_funnel.sql
│   │       ├── 04_stocks_yesterday.sql
│   │       ├── 05_ads.sql
│   │       ├── 06_kpi_30d.sql
│   │       └── 07_finance_ops_daily.sql
│   │
│   ├── docs/                   # Операционная документация
│   │   ├── architecture.md     # Архитектура и потоки данных
│   │   ├── environments.md     # dev / stage / prod
│   │   ├── observability.md    # Метрики, алерты, Grafana
│   │   ├── disaster_recovery.md # Бэкапы, RPO/RTO, процедуры восстановления
│   │   ├── credential_rotation.md # Ротация секретов
│   │   ├── migration_policy.md # Политика миграций БД
│   │   ├── performance.md      # Нагрузочные цели и результаты
│   │   ├── runbooks.md         # Операторские процедуры
│   │   ├── troubleshooting.md  # Диагностика проблем
│   │   ├── release_management.md # Версионирование и деплой
│   │   └── ...
│   │
│   ├── infra/                  # Инфраструктура
│   │   ├── docker/
│   │   │   ├── docker-compose.yml  # Полный стек (7 сервисов)
│   │   │   ├── clickhouse/         # Конфигурация ClickHouse
│   │   │   ├── metabase/           # Конфигурация Metabase
│   │   │   └── nginx/              # Конфигурация Nginx + TLS-сертификаты
│   │   ├── monitoring/
│   │   │   └── prometheus/         # Prometheus config + alert rules
│   │   └── nginx/
│   │       ├── nginx.conf
│   │       └── certs/              # Самоподписанные сертификаты (dev)
│   │
│   ├── scripts/                # Утилиты оператора
│   │   ├── bootstrap.sh        # Полная инициализация стека
│   │   ├── backfill.py         # Ручной бэкфилл данных
│   │   ├── check_tokens.py     # Проверка токенов API
│   │   ├── perf_smoke.py       # Нагрузочный дымовой тест
│   │   ├── provision_clickhouse_users.py  # Создание пользователей ClickHouse
│   │   └── run_local.sh        # Локальный запуск
│   │
│   ├── tests/                  # Тестовое покрытие
│   │   ├── fixtures/           # Фикстуры (JSON-ответы API)
│   │   ├── integration/        # Интеграционные тесты
│   │   └── unit/               # Юнит-тесты
│   │
│   ├── warehouse/              # Схема БД и миграции
│   │   ├── apply_migrations.py # Скрипт применения миграций
│   │   ├── ddl/                # Справочные DDL
│   │   └── migrations/         # Последовательные SQL-миграции
│   │       ├── 0001_init.sql   # Системные таблицы, dimensions, raw-слой
│   │       ├── 0002_stg.sql    # Staging-слой
│   │       ├── 0003_marts.sql  # Mart-слой (агрегаты)
│   │       └── 0004_finance.sql # Финансовые таблицы
│   │
│   ├── workers/                # Celery-воркеры
│   │   ├── Dockerfile
│   │   └── app/
│   │       ├── celery_app.py   # Конфигурация Celery-приложения
│   │       ├── beat_schedule.py # Расписание всех периодических задач
│   │       └── tasks/          # Задачи
│   │           ├── wb_collect.py    # Сборщики WB
│   │           ├── ozon_collect.py  # Сборщики Ozon
│   │           ├── transforms.py    # raw → stg трансформации
│   │           ├── marts.py         # stg → mrt агрегации
│   │           └── maintenance.py   # Автоматизация, очистка, data quality
│   │
│   ├── pyproject.toml          # Python-конфигурация (black, ruff, mypy)
│   ├── pytest.ini              # Настройки pytest
│   ├── requirements.txt        # Зафиксированные production-зависимости
│   └── requirements-dev.txt    # Зависимости для разработки
│
├── CONTRIBUTING.md             # Правила контрибуции
├── SECURITY.md                 # Политика безопасности
├── CODE_OF_CONDUCT.md          # Кодекс поведения
├── LICENSE                     # Лицензия
└── Makefile                    # Корневой Makefile (обёртка)
```

---

## Быстрый старт

### Предварительные требования

- **Docker** и **Docker Compose** (v2)
- **Python 3.12** (для локальной разработки и скриптов)
- **make** (для удобных команд)
- Активные продавческие аккаунты на Wildberries и/или Ozon с API-токенами

### Установка и запуск

1. Склонируйте репозиторий:

```bash
git clone https://github.com/Bormotoon/BormoStats.git
cd BormoStats
```

2. Скопируйте и заполните файл окружения:

```bash
cd marketplace-analytics
cp .env.example .env
```

> Для разных сред доступны шаблоны: `.env.dev.example`, `.env.stage.example`, `.env.prod.example`

3. Заполните **обязательные** секреты в `.env` (подробности в секции [Конфигурация](#конфигурация)).

> ⚠️ Bootstrap завершится с ошибкой, если в `.env` остались плейсхолдеры или пустые обязательные поля.

4. Запустите полный стек:

```bash
cd ..
make bootstrap
```

Скрипт `bootstrap` последовательно:
- Валидирует секреты (быстрый отказ при плейсхолдерах)
- Проверяет конфликты портов
- Запускает ClickHouse и Redis
- Создаёт пользователей ClickHouse (bootstrap admin → app users)
- Применяет SQL-миграции
- Запускает backend, worker, beat, metabase, nginx
- Проводит health-проверки и дымовые тесты токенов

### Проверка здоровья

```bash
# Health-check (через HTTP-прокси)
curl http://localhost:18080/health

# Readiness (через HTTPS-прокси)
curl -k https://localhost:18443/ready

# Метрики Prometheus
curl -k https://localhost:18443/metrics
```

Откройте веб-интерфейс:

```bash
xdg-open https://localhost:18443/ui/
```

---

## Конфигурация

### Обязательные переменные окружения

| Переменная | Назначение |
|---|---|
| `BOOTSTRAP_CH_ADMIN_USER` | Администраторский пользователь ClickHouse (для миграций) |
| `BOOTSTRAP_CH_ADMIN_PASSWORD` | Пароль администратора ClickHouse |
| `CH_USER` | Пользователь ClickHouse для приложения |
| `CH_PASSWORD` | Пароль пользователя ClickHouse |
| `ADMIN_API_KEY` | Ключ доступа к admin API (генерация: `openssl rand -hex 32`) |
| `WB_TOKEN_STATISTICS` | Токен WB для статистических эндпоинтов |
| `WB_TOKEN_ANALYTICS` | Токен WB для аналитических эндпоинтов |
| `OZON_CLIENT_ID` | Client ID Ozon |
| `OZON_API_KEY` | API-ключ Ozon |

### Опциональные переменные

| Переменная | Назначение |
|---|---|
| `OZON_PERF_API_KEY` | API-ключ Ozon Performance (для рекламных данных) |
| `WB_TOKEN_CREATED_AT` | Дата создания WB-токена (для напоминаний об истечении, токены действуют 180 дней) |
| `CH_RO_USER` / `CH_RO_PASSWORD` | Read-only пользователь ClickHouse для Metabase |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | Telegram-бот для уведомлений автоматизации |
| `CH_HTTP_HOST_PORT` | Host-порт ClickHouse (по умолчанию `18123`) |
| `BACKEND_HOST_PORT` | Host-порт HTTP (по умолчанию `18080`) |
| `BACKEND_TLS_HOST_PORT` | Host-порт HTTPS (по умолчанию `18443`) |
| `METABASE_HOST_PORT` | Host-порт Metabase (по умолчанию `13000`) |
| `STACK_NAME` | Имя Docker Compose-стека (для изоляции сред) |
| `*_MEMORY_LIMIT` / `*_CPU_LIMIT` | Лимиты ресурсов контейнеров |
| `CH_POOL_MAXSIZE` | Размер пула HTTP-соединений ClickHouse (по умолчанию `16`) |

### Порты по умолчанию

| Сервис | Порт | Область |
|---|---|---|
| Backend HTTP (nginx) | `18080` | Публичный |
| Backend HTTPS (nginx) | `18443` | Публичный |
| Metabase | `13000` | Loopback |
| ClickHouse HTTP | `18123` | Loopback |
| Worker metrics | `19101` | Loopback |
| Beat metrics | `19102` | Loopback |

> **Совет:** если порты конфликтуют с другими сервисами, измените значения в `.env`.

---

## Веб-интерфейс

BormoStats включает встроенный веб-интерфейс в стиле Material 3 с тёмной темой, доступный по адресу `https://localhost:18443/ui/`.

Возможности:
- **Dashboard** — операционный обзор с ключевыми метриками
- **Страницы по доменам** — продажи, остатки, воронка, реклама, KPI
- **Админ-панель** — управление бэкфиллами, трансформами, мартами, задачами
- **Настройки** — API Base URL и Admin API Key (хранится только в памяти текущей вкладки)

> Ключ администратора хранится **только в памяти текущей вкладки**. При перезагрузке или открытии новой вкладки его нужно вводить заново.

---

## API

### Публичные эндпоинты аналитики

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/v1/sales/daily` | Ежедневные продажи |
| `GET` | `/api/v1/stocks/current` | Текущие остатки |
| `GET` | `/api/v1/funnel/daily` | Ежедневная воронка (просмотры → корзина → заказы) |
| `GET` | `/api/v1/ads/daily` | Ежедневная реклама |
| `GET` | `/api/v1/kpis` | Ключевые показатели эффективности |

**Параметры запросов:**
- `marketplace` — фильтр по маркетплейсу (`wb` или `ozon`)
- `account_id` — ID аккаунта
- `date_from` / `date_to` — диапазон дат (максимум 92 дня)
- `limit` / `offset` — пагинация

**Формат ошибок:** `{"detail":"...","error":{"code":"...","message":"..."}}`

### Административные эндпоинты

Требуют заголовок `X-API-Key`.

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/v1/admin/watermarks` | Текущие водяные знаки (курсоры инкрементального сбора) |
| `POST` | `/api/v1/admin/backfill` | Запуск бэкфилла данных |
| `POST` | `/api/v1/admin/transforms/recent` | Запуск трансформов за последний период |
| `POST` | `/api/v1/admin/transforms/backfill` | Бэкфилл трансформов |
| `POST` | `/api/v1/admin/marts/recent` | Пересборка мартов за последний период |
| `POST` | `/api/v1/admin/marts/backfill` | Бэкфилл мартов |
| `POST` | `/api/v1/admin/maintenance/run-automation` | Ручной запуск правил автоматизации |
| `POST` | `/api/v1/admin/maintenance/prune-raw` | Очистка старых raw-данных |
| `GET` | `/api/v1/admin/task-runs` | История запусков задач (аудит) |

---

## Сбор данных

### Wildberries

Клиент `WbApiClient` использует два токена для разных групп эндпоинтов:

| Метод | Данные | Токен |
|---|---|---|
| `sales_since()` | Инкрементальные продажи | `WB_TOKEN_STATISTICS` |
| `orders_since()` | Инкрементальные заказы | `WB_TOKEN_STATISTICS` |
| `stocks()` | Снимок остатков | `WB_TOKEN_STATISTICS` |
| `funnel_daily()` | Воронка (просмотры, корзины, заказы) | `WB_TOKEN_ANALYTICS` |

### Ozon

Клиент `OzonApiClient` использует Client ID + API Key, плюс опциональный Performance API Key:

| Метод | Данные | Ключ |
|---|---|---|
| `postings_since()` | Отправления (FBS/FBO) с пагинацией | `OZON_API_KEY` |
| `stocks()` | Снимок остатков | `OZON_API_KEY` |
| `ads_daily()` | Рекламная статистика | `OZON_PERF_API_KEY` |
| `finance_ops()` | Финансовые операции | `OZON_API_KEY` |

### Инфраструктура сборщиков

- **HTTP-клиент** (`JsonHttpClient`) с настраиваемым таймаутом (по умолчанию 30с), гранулярными connect/read/write таймаутами
- **Экспоненциальный backoff с jitter** для повторов при 5xx-ошибках
- **WB-специфичная обработка 429** через заголовок `X-Retry-After`
- **Circuit breaker** (5 ошибок → 60 секунд ожидания)
- **Redis-блокировки** (`lock:{source}:{account_id}`) для предотвращения параллельного сбора из одного источника
- **Водяные знаки** (`sys_watermarks`) для инкрементального сбора без пропусков и дублей
- **Редакция** чувствительных заголовков в логах

### Расписание задач

#### Wildberries
| Задача | Частота |
|---|---|
| `wb_sales_incremental` | каждые 15 мин |
| `wb_orders_incremental` | каждые 15 мин |
| `wb_stocks_snapshot` | каждые 30 мин |
| `wb_funnel_roll` | каждый час в :05 |
| `wb_sales_backfill_14d` | ежедневно в 03:10 |
| `wb_orders_backfill_14d` | ежедневно в 03:20 |
| `wb_funnel_backfill_14d` | ежедневно в 03:30 |

#### Ozon
| Задача | Частота |
|---|---|
| `ozon_postings_incremental` | каждые 20 мин |
| `ozon_stocks_snapshot` | каждые 30 мин |
| `ozon_finance_incremental` | каждые 6 часов в :50 |
| `ozon_ads_daily` | каждые 6 часов в :40 |

#### ELT и витрины
| Задача | Частота |
|---|---|
| `transform_raw_to_stg` | каждые 30 мин (в :05 и :35) |
| `build_marts_recent` | каждые 30 мин (в :20 и :50) |
| `build_marts_backfill_14d` | ежедневно в 04:20 |

#### Обслуживание
| Задача | Частота |
|---|---|
| `automation_rules_run` | 3 раза/день (09:00, 15:00, 21:00) |
| `maintenance_prune_raw` | ежедневно в 02:00 |
| `maintenance_data_quality_checks` | каждый час в :58 |

#### Маршрутизация очередей Celery

| Очередь | Задачи |
|---|---|
| `wb` | `tasks.wb_collect.*` |
| `ozon` | `tasks.ozon_collect.*` |
| `etl` | `tasks.transforms.*`, `tasks.marts.*` (и по умолчанию) |
| `automation` | `tasks.maintenance.run_automation_rules` |

---

## Хранилище данных (ClickHouse)

БД `mp_analytics` использует ClickHouse с движком ReplacingMergeTree и партиционированием по месяцам.

### Миграции

Миграции применяются последовательно скриптом `warehouse/apply_migrations.py`:

| Файл | Содержимое |
|---|---|
| `0001_init.sql` | Системные таблицы, измерения, raw-слой WB + Ozon |
| `0002_stg.sql` | Каноническая staging-модель |
| `0003_marts.sql` | Агрегированные витрины |
| `0004_finance.sql` | Финансовые таблицы |

Версионирование отслеживается в `sys_schema_migrations`. Политика миграций — **forward-only** (без откатов).

### Raw-слой

**Wildberries:**
- `raw_wb_sales` — srid, event_ts, nm_id, chrt_id, quantity, price_rub, is_return
- `raw_wb_orders` — srid, event_ts, nm_id, chrt_id, quantity, price_rub
- `raw_wb_stocks` — snapshot_ts, nm_id, chrt_id, warehouse_id, amount
- `raw_wb_funnel_daily` — day, nm_id, views, carts, orders, conversions...

**Ozon:**
- `raw_ozon_postings` — posting_number, status, created_at, shipped_at, delivered_at, canceled_at
- `raw_ozon_posting_items` — ozon_product_id, offer_id, quantity, price
- `raw_ozon_stocks` — ozon_product_id, warehouse_id, present, reserved
- `raw_ozon_ads_daily` — day, campaign_id, impressions, clicks, cost, orders, revenue
- `raw_ozon_finance_ops` — operation_id, operation_ts, type, amount

### Staging-слой

Каноническая модель с маппингом полей из WB и Ozon в единую схему:

- `stg_sales` — event_ts, product_id, quantity, price_gross, marketplace, day (materialized)
- `stg_orders` — аналогичная структура
- `stg_stocks` — product_id, warehouse_id, amount
- `stg_funnel_daily` — views, carts, orders, conversions
- `stg_ads_daily` — impressions, clicks, cost, orders, revenue
- `stg_finance_ops` — финансовые операции

### Мартовый слой

Агрегированные витрины для BI и API:

- `mrt_sales_daily` — агрегат продаж по дням
- `mrt_stock_daily` — агрегат остатков по дням
- `mrt_funnel_daily` — агрегат воронки по дням
- `mrt_ads_daily` — агрегат рекламы по дням

### Системные таблицы

| Таблица | Назначение |
|---|---|
| `sys_schema_migrations` | Отслеживание применённых миграций |
| `sys_watermarks` | Курсоры инкрементального сбора (ReplacingMergeTree) |
| `sys_task_runs` | Аудит-лог задач: статус, количество строк, сообщения, meta_json |
| `dim_marketplace` | Справочник маркетплейсов (wb, ozon) |
| `dim_account` | Справочник аккаунтов |
| `dim_product` | Справочник товаров (marketplace + account + product_id) |

---

## Автоматизация и уведомления

Движок правил автоматизации (`automation/engine.py`) использует YAML-файлы для описания бизнес-правил.

### Как работает

1. Для каждого правила выполняется SQL-запрос к ClickHouse
2. Результаты проверяются через **безопасный AST-вычислитель** (без `exec`/`eval`) — разрешены арифметика, сравнения, булева логика и функции `min`, `max`, `round` и др.
3. При выполнении условия запускается действие (Telegram-уведомление)

### Предустановленные правила

| Правило | Условие | Действие |
|---|---|---|
| `bad_acos.yml` | Выручка > 0 **И** ACOS > 30% за прошлый день | Telegram-алерт |
| `low_stock.yml` | Остатки ниже порога | Telegram-алерт |
| `no_sales_7d.yml` | Нет продаж за 7 дней | Telegram-алерт |

### Настройка Telegram

1. Установите `TG_BOT_TOKEN` и `TG_CHAT_ID` в `.env`
2. Убедитесь, что задача `tasks.maintenance.run_automation_rules` активна в beat-расписании
3. Адаптируйте пороги в файлах `automation/rules/*.yml`

---

## Дашборды

### Встроенные SQL-дашборды

| Файл | Описание |
|---|---|
| `01_sales_overview.sql` | Обзор продаж |
| `02_top_products_30d.sql` | Топ товаров за 30 дней |
| `03_funnel.sql` | Воронка продаж |
| `04_stocks_yesterday.sql` | Остатки за вчера |
| `05_ads.sql` | Рекламная аналитика |
| `06_kpi_30d.sql` | KPI за 30 дней |
| `07_finance_ops_daily.sql` | Ежедневные финансовые операции |

### Grafana-дашборды

- `operational_overview.json` — операционный обзор (задачи, ошибки, потребление ресурсов)
- `ingestion_freshness.json` — свежесть данных (лаг водяных знаков)

> Для импорта в Grafana: используйте datasource с именем `prometheus` или обновите UID в JSON.

### Metabase

После запуска стека Metabase доступен на `http://localhost:13000`. Подключите его к ClickHouse, используя credentials приложения или read-only пользователя (`CH_RO_USER`).

---

## Мониторинг и наблюдаемость

### Prometheus-метрики

**Бэкенд** (`/metrics`):
- `service_readiness{service="redis|clickhouse"}` — готовность зависимостей
- `redis_memory_used_bytes`, `redis_memory_limit_bytes`, `redis_memory_utilization_ratio`
- `clickhouse_disk_free_bytes`, `clickhouse_disk_total_bytes`, `clickhouse_disk_free_ratio`

**Worker** (`localhost:19101/metrics`) и **Beat** (`localhost:19102/metrics`):
- Счётчики/гейджи/гистограммы: строки, длительности, лаг водяных знаков, пустые payload-ы

### Алерт-правила

| Правило | Что отслеживает |
|---|---|
| `MarketplaceTaskFailures` | Ошибки в задачах сбора/трансформов |
| `MarketplaceWatermarkStale` | Устаревшие водяные знаки (данные не обновляются) |
| `MarketplaceEmptyPayloadAnomaly` | Аномально пустые ответы API |
| `RedisMemorySaturation` | Высокое потребление памяти Redis |
| `RedisUnavailable` | Redis недоступен |
| `ClickHouseUnavailable` | ClickHouse недоступен |
| `ClickHouseDiskPressure` | Мало свободного места на диске ClickHouse |

### Проверка алертов

```bash
promtool test rules infra/monitoring/prometheus/alerts.test.yml
```

---

## Безопасность

### Runtime-ограничения

- Контейнеры `backend`, `worker` и `beat` работают от непривилегированного пользователя `app` (uid/gid `10001`)
- `read_only: true` — файловая система контейнеров доступна только на чтение
- `no-new-privileges` — запрет эскалации привилегий
- `tmpfs` для `/tmp` — запись только во временную файловую систему
- Публичная точка входа — **только** nginx reverse proxy; бэкенд не публикуется напрямую
- Loopback-only порты (ClickHouse, Metabase, метрики) на отдельной сети `ops`
- Redis изолирован в приватной Docker-сети без публикации портов

### Принцип наименьших привилегий

- Admin API ограничен типизированным белым списком эндпоинтов
- Админ-ключ в веб-UI хранится только в памяти вкладки
- ClickHouse-приложение использует отдельного пользователя (не bootstrap admin)
- Worker и beat изолированы от публичной сети
- Опциональный read-only пользователь ClickHouse для Metabase

### Ротация секретов

Подробные инструкции по ротации всех типов credentials — в `docs/credential_rotation.md`:
- WB-токены (действуют 180 дней)
- Ozon Client ID / API Key
- Admin API Key
- ClickHouse credentials
- Telegram-секреты

### Политика сообщения об уязвимостях

Не открывайте публичные issues для security-проблем. Используйте GitHub Private Vulnerability Reporting или свяжитесь с мейнтейнером напрямую. Подробности — в `SECURITY.md`.

---

## Среды (dev / stage / prod)

Проект поддерживает три изолированные среды:

| Среда | Назначение | Шаблон |
|---|---|---|
| `dev` | Локальная разработка, self-signed TLS, одноразовые данные | `.env.dev.example` |
| `stage` | Production-like валидация на изолированных credentials | `.env.stage.example` |
| `prod` | Только бизнес-трафик, минимальные привилегии | `.env.prod.example` |

### Разделение портов по средам

| Среда | Stack name | HTTP | HTTPS | ClickHouse | Metabase | Worker | Beat |
|---|---|---|---|---|---|---|---|
| dev | `bormostats-dev` | 18080 | 18443 | 18123 | 13000 | 19101 | 19102 |
| stage | `bormostats-stage` | 28080 | 28443 | 28123 | 23000 | 29101 | 29102 |
| prod | `bormostats-prod` | 38080 | 38443 | 38123 | 33000 | 39101 | 39102 |

### Промоушн-флоу

1. Разработка и валидация изменений в `dev`
2. Промоушн того же коммита в `stage`
3. Полный quality gate, bootstrap/migration smoke checks, release checklist в `stage`
4. Промоушн того же коммита и pinned-образов в `prod` **без пересборки артефактов**
5. При провале верификации — откат к последнему рабочему коммиту/образам

> ⚠️ **Никогда** не переиспользуйте секреты (токены, ключи, пароли) между средами.

---

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`) включает 4 job-а:

### 1. `lint-test` — Проверка качества кода
- **Ruff** — линтинг (select: E, F, I, B, UP, N, RUF)
- **Black** — форматирование (line-length: 100)
- **MyPy** — строгая статическая типизация (strict mode)
- **Pytest** — запуск тестов

### 2. `docker-build` — Сборка Docker-образов
- Сборка `backend` и `worker` образов

### 3. `supply-chain` — Безопасность цепочки поставок
- **pip-audit** — сканирование уязвимостей Python-зависимостей
- **Anchore Grype** — сканирование Docker-образов (fail на high severity)
- **SBOM-генерация** (SPDX JSON) для исходников и образов
- **SARIF upload** в GitHub Security для визуализации результатов

### 4. `migration-smoke` — Дымовой тест миграций
- Запуск ClickHouse в CI
- Создание пользователей
- Применение всех миграций
- Верификация схемы (проверка 4 ключевых таблиц + записи в `sys_schema_migrations`)

### Дополнительно
- **Dependabot** — автоматическое обновление зависимостей
- **Concurrency group** — отмена предыдущих запусков при новых push-ах
- Шаблоны для **issues** и **pull requests**

---

## Тестирование

```bash
# Юнит и интеграционные тесты
make test

# Полная проверка (lint + format + typecheck + test)
make check

# Нагрузочный дымовой тест
make perf-smoke

# Проверка Docker Compose конфига
make docker-config
```

### Структура тестов

- `tests/unit/` — юнит-тесты (парсеры, валидация, бизнес-логика)
- `tests/integration/` — интеграционные тесты (admin API, полные сценарии)
- `tests/fixtures/` — JSON-фикстуры (пример: `ozon_cancelled_posting.json`)

---

## Полезные команды

### Корневой Makefile

```bash
make bootstrap       # Полная инициализация стека
make lint            # Линтинг (Ruff)
make format          # Форматирование (Black)
make typecheck       # Статическая типизация (MyPy)
make test            # Запуск тестов (pytest)
make check           # lint + black-check + typecheck + test
make check-tokens    # Проверка API-токенов
make perf-smoke      # Нагрузочный дымовой тест
make docker-config   # Валидация docker-compose.yml
```

### Проектный Makefile (`marketplace-analytics/`)

```bash
make up              # Запуск стека
make down            # Остановка стека
make logs            # Просмотр логов контейнеров
make ps              # Статус контейнеров
make migrate         # Применение миграций
```

### Ручной бэкфилл данных

```bash
# WB — продажи за 14 дней
python3 scripts/backfill.py --marketplace wb --dataset sales --days 14 --api-key <KEY>

# Ozon — финансы за 30 дней
python3 scripts/backfill.py --marketplace ozon --dataset finance --days 30 --api-key <KEY>
```

---

## Устранение неполадок

| Проблема | Решение |
|---|---|
| API rate limits (429) / upstream ошибки (5xx) | См. `docs/troubleshooting.md`, секция «429/5xx» |
| Нет новых данных | Проверьте водяные знаки (`/api/v1/admin/watermarks`) и запустите ручной бэкфилл |
| Ошибки premium/capability у Ozon | Проверьте `sys_task_runs.meta_json` через admin API |
| Конфликт портов | Измените `*_HOST_PORT` переменные в `.env` |
| Bootstrap падает | Убедитесь, что все обязательные секреты заполнены (не плейсхолдеры) |
| ClickHouse недоступен | `docker compose logs clickhouse`, проверьте credentials |

Подробнее: `docs/troubleshooting.md` и `docs/runbooks.md`.

---

## Резервное копирование и восстановление

### Что бэкапить

| Актив | Объём | Метод |
|---|---|---|
| ClickHouse volume (`${STACK_NAME}_ch_data`) | Основной | Архивация Docker volume |
| Metabase volume (`${STACK_NAME}_metabase_data`) | Метаданные | Архивация Docker volume |
| `.env` и секреты | Критические | Secret manager / зашифрованная копия |

### Пример бэкапа ClickHouse

```bash
docker run --rm \
  -v ${STACK_NAME}_ch_data:/source:ro \
  -v "$(pwd)/backups:/backup" \
  busybox:1.36.1 \
  sh -c 'cd /source && tar czf /backup/clickhouse-$(date +%Y%m%dT%H%M%S).tar.gz .'
```

### RPO / RTO

| Актив | RPO | RTO |
|---|---|---|
| ClickHouse | 24ч + ручной бэкап перед релизами | 2ч |
| Metabase | 24ч | 30 мин |
| Секреты | 1ч после каждого изменения | 1ч |

Подробнее: `docs/disaster_recovery.md`.

---

## Разработка и Contributing

### Локальная настройка

```bash
cd marketplace-analytics
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
```

### Перед отправкой PR

```bash
make lint               # Ruff
./.venv/bin/black --check .   # Black
make typecheck          # MyPy (strict)
make test               # pytest
```

### Политика зависимостей

- `requirements.txt` и `requirements-dev.txt` — **полностью зафиксированные** версии
- Docker-образы в `docker-compose.yml` — **закреплены по digest**
- Обновления зависимостей — только из чистого virtualenv с повторным прогоном всех проверок
- CI также запускает `pip-audit`, сканирование Docker-образов и генерацию SBOM

Подробнее: `CONTRIBUTING.md`.

---

## Документация

| Документ | Содержание |
|---|---|
| [marketplace-analytics/README.md](marketplace-analytics/README.md) | Runtime-гайд, API, операционные guardrails |
| [docs/architecture.md](marketplace-analytics/docs/architecture.md) | Архитектура и потоки данных |
| [docs/environments.md](marketplace-analytics/docs/environments.md) | Модель сред dev/stage/prod |
| [docs/observability.md](marketplace-analytics/docs/observability.md) | Метрики, алерты, Grafana |
| [docs/disaster_recovery.md](marketplace-analytics/docs/disaster_recovery.md) | Бэкапы, RPO/RTO, восстановление |
| [docs/credential_rotation.md](marketplace-analytics/docs/credential_rotation.md) | Ротация секретов |
| [docs/migration_policy.md](marketplace-analytics/docs/migration_policy.md) | Политика миграций |
| [docs/performance.md](marketplace-analytics/docs/performance.md) | Нагрузочные цели и результаты |
| [docs/runbooks.md](marketplace-analytics/docs/runbooks.md) | Операторские процедуры |
| [docs/troubleshooting.md](marketplace-analytics/docs/troubleshooting.md) | Диагностика проблем |
| [docs/release_management.md](marketplace-analytics/docs/release_management.md) | Управление релизами |
| [docs/supply_chain_security.md](marketplace-analytics/docs/supply_chain_security.md) | Безопасность цепочки поставок |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Правила контрибуции |
| [SECURITY.md](SECURITY.md) | Политика безопасности |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Кодекс поведения |

---

## Лицензия

См. файл [LICENSE](LICENSE).
