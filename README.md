<picture>
  <source media="(prefers-color-scheme: dark)" srcset="screenshots/dashboard.png">
  <img src="screenshots/dashboard.png" alt="BormoStats Dashboard" width="100%">
</picture>

<div align="center">

# 📊 BormoStats

**Self-hosted marketplace analytics for Wildberries & Ozon sellers**

[![CI](https://github.com/Bormotoon/BormoStats/actions/workflows/ci.yml/badge.svg)](https://github.com/Bormotoon/BormoStats/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.14-%233776AB?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-%23009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-%2361DAFB?logo=react)](https://react.dev/)
[![ClickHouse](https://img.shields.io/badge/ClickHouse-26.x-%23FCC624?logo=clickhouse)](https://clickhouse.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-multi--stage-%232496ED?logo=docker)](https://docker.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](/CONTRIBUTING.md)

---

<p align="center">
  <a href="README.ru.md"><strong>Русский</strong></a> •
  <strong>English</strong>
</p>

[Features](#-features) • [Quick Start](#-quick-start) • [Architecture](#-architecture) • [Screenshots](#-screenshots) • [API](#-api) • [Configuration](#-configuration) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## 🚀 Features

| Capability | Description |
|---|---|
| **Automated Data Collection** | Incremental collection of sales, orders, stocks, funnels, ads, and finances from WB & Ozon APIs |
| **Analytics Warehouse** | Three-layer data warehouse in ClickHouse (raw → staging → marts) |
| **REST API** | FastAPI backend with endpoints for sales, stocks, funnels, ads, and KPIs |
| **Modern Web UI** | Built-in React 19 SPA with dark theme, dashboards, and admin panel |
| **BI Dashboards** | Metabase integration for custom dashboards and ad-hoc SQL queries |
| **Telegram Alerts** | YAML-defined automation rules: high ACOS, low stock, no sales |
| **Admin API** | Backfill, transforms, watermarks, task audit, and maintenance operations |
| **Observability** | Prometheus metrics, Grafana dashboards, alert rules |
| **Supply Chain Security** | pip-audit, Docker image scanning (Grype), SBOM generation (SPDX) |

### Project Boundaries

- ✅ Collects data **only** from your own seller accounts
- ✅ Fully self-hosted — no data sent to third parties
- ❌ Does not scrape competitor data or marketplace catalogues
- ❌ Does not provide market-wide analytics

---

## 🖼️ Screenshots

| Page | Preview | Description |
|---|---|---|
| **Dashboard** | ![Dashboard](screenshots/dashboard.png) | Operational overview: service health, revenue, sales qty, ad cost, stock units, revenue/ad spend trends, top products table |
| **Sales** | ![Sales](screenshots/sales.png) | Daily sales analytics: aggregated revenue, qty, returns, payout — trend chart and full data table with marketplace/account filters |
| **Stocks** | ![Stocks](screenshots/stocks.png) | Current inventory: total stock count, low-stock alerts, warehouse breakdown, top products bar chart |
| **Funnel** | ![Funnel](screenshots/funnel.png) | Conversion funnel: views, adds-to-cart, orders — with CR order/cart averages, daily orders trend |
| **Ads** | ![Ads](screenshots/ads.png) | Advertising performance: cost, revenue, clicks, orders, ACOS, ROMI — dual trend charts (cost vs revenue by day) |
| **KPIs** | ![KPIs](screenshots/kpis.png) | 30-day KPIs: revenue, qty, returns, ad cost aggregated by marketplace/account with bar chart |
| **Watermarks** | ![Watermarks](screenshots/watermarks.png) | Admin — ingestion watermarks cursor table showing data source sync status (wb_sales, ozon_postings, etc.) |
| **Task Runs** | ![Task Runs](screenshots/taskRuns.png) | Admin — worker task audit log with run status, rows ingested, error messages |
| **Admin Actions** | ![Admin Actions](screenshots/adminActions.png) | Admin — backfill, transform, and maintenance operations panel with day-range input and response viewer |
| **System** | ![System](screenshots/system.png) | Service health, readiness, and Prometheus metrics sample

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CELERY BEAT (Scheduler)                          │
│    Schedules collectors, transforms, marts, automation, pruning    │
└────────────┬────────────────┬──────────────────┬───────────────────┘
             │                │                  │
             ▼                ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌───────────────────────────┐
│  WB Collector   │ │  Ozon Collector │ │  Transforms & Marts       │
│  (API client)   │ │  (API client)   │ │  (SQL transformations)   │
└────────┬────────┘ └────────┬────────┘ └─────────────┬─────────────┘
         │                   │                        │
         ▼                   ▼                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     CLICKHOUSE (Data Warehouse)                       │
│    raw_* → stg_* → mrt_*  |  sys_watermarks  |  sys_task_runs       │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────┐
│              FastAPI Backend                           │
│  /api/v1/* (analytics)  /api/v1/admin/* (admin)      │
│  /ui (web UI)  /metrics (Prometheus)                  │
└─────────────────────────┬─────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────┐  ┌──────────────┐
│  Nginx Reverse Proxy (TLS)  │  │   Metabase   │
│  → public entry point        │  │  (BI dashboards)│
└──────────────────────────────┘  └──────────────┘
```

### Components

| Component | Technology | Purpose |
|---|---|---|
| **Backend** | FastAPI + Uvicorn | REST API, web UI, health/ready/metrics |
| **Worker** | Celery | Data collection, transforms, marts, automation |
| **Beat** | Celery Beat | Periodic task scheduler |
| **ClickHouse** | ClickHouse 26.x | OLAP analytics warehouse |
| **Redis** | Redis 7.x | Celery broker + distributed locks |
| **Nginx** | Nginx 1.27 | Reverse proxy with TLS termination |
| **Metabase** | Metabase | BI platform for dashboards |
| **Prometheus** | Prometheus | Metrics collection and alerting |

### Data Pipeline

Data flows through three processing layers:

1. **Raw layer** (`raw_*`) — Raw API responses with JSON payloads and normalized key fields for idempotent ingestion
2. **Staging layer** (`stg_*`) — Canonical normalized model with unified schema across WB and Ozon
3. **Mart layer** (`mrt_*`) — Aggregated BI views ready for dashboards and API consumption

### Tech Stack

| Category | Technologies |
|---|---|
| **Language** | Python 3.14 |
| **Web Framework** | FastAPI 0.135, Uvicorn 0.41 |
| **Task Queue** | Celery 5.6, Redis 7.2 |
| **Storage** | ClickHouse 26.x (clickhouse-connect 0.13) |
| **Frontend** | React 19, Vite 8, Tailwind CSS 4, Recharts 3, Motion |
| **HTTP Client** | httpx 0.28 |
| **Validation** | Pydantic 2.12, pydantic-settings 2.13 |
| **Metrics** | prometheus_client 0.24 |
| **Logging** | structlog 25.5 (structured JSON) |
| **Automation** | PyYAML 6.0 (YAML rules engine) |
| **BI** | Metabase (Docker) |
| **Infrastructure** | Docker Compose, Nginx, Prometheus, Grafana |
| **Linting** | Ruff 0.15 |
| **Typing** | MyPy 1.19 (strict mode) |
| **Tests** | pytest 9.0, pytest-asyncio |
| **Security** | pip-audit, Anchore Grype, SPDX SBOM |

---

## ⚡ Quick Start

### Prerequisites

- Active Wildberries and/or Ozon seller accounts with API tokens
- **make** (for convenience commands)

### Option A: Docker (recommended)

Requires **Docker** & **Docker Compose v2**.

```bash
git clone https://github.com/Bormotoon/BormoStats.git
cd BormoStats
cp .env.example .env
```

Edit `.env` and set **at minimum** these values:

| Variable | Where to get it |
|---|---|
| `WB_STATISTICS_API_KEY` | Wildberries → Личный кабинет → Настройки → API |
| `OZON_CLIENT_ID` | Ozon → Настройки → API |
| `OZON_API_KEY` | Ozon → Настройки → API |
| `ADMIN_API_KEY` | Generate: `openssl rand -hex 32` |

```bash
make up
```

This starts ClickHouse, Redis, Backend, Worker, Beat, Nginx (TLS), Metabase — all containerized.

> 💡 First build takes 3–5 minutes. Subsequent builds use Docker layer caching.

```bash
# Health check
curl http://localhost:18080/health

# Web UI
open https://localhost:18443/ui/

# Metabase BI
open http://localhost:13000
```

### Option B: OS (bare metal)

Requires **Python 3.14+**, **Node.js 22+**, **ClickHouse**, and **Redis** installed on the host.

```bash
git clone https://github.com/Bormotoon/BormoStats.git
cd BormoStats
cp .env.example .env
```

Edit `.env` as above, then:

```bash
make install
make run
```

`make install` creates a venv, installs deps, builds the frontend, and applies migrations.
`make run` starts Backend (uvicorn), Celery Worker, and Celery Beat in a single terminal.

For production, use the provided systemd units:

```bash
sudo make install-systemd
```

---

## 🖥️ Web UI

The built-in React SPA is available at `https://localhost:18443/ui/`. It features:

- **Dashboard** — Operational overview with key metrics and charts
- **Sales** — Daily sales analytics with filters
- **Stocks** — Current stock levels by warehouse
- **Funnel** — Conversion funnel (views → cart → orders)
- **Ads** — Advertising performance metrics
- **KPIs** — Key performance indicators over time
- **Watermarks** — Ingestion watermark cursors (admin)
- **Task Runs** — Worker task audit log (admin)
- **Admin Actions** — Backfill, transform, mart management, maintenance operations
- **System** — Service health, readiness, Prometheus metrics

> 🔐 The admin key is stored **in session memory only**. It must be re-entered after closing the tab or refreshing the page.

---

## 📡 API

### Public Analytics Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/sales/daily` | Daily sales |
| `GET` | `/api/v1/stocks/current` | Current stock levels |
| `GET` | `/api/v1/funnel/daily` | Daily funnel (views → cart → orders) |
| `GET` | `/api/v1/ads/daily` | Daily advertising |
| `GET` | `/api/v1/kpis` | Key performance indicators |

**Query Parameters:**
- `marketplace` — filter by marketplace (`wb` or `ozon`)
- `account_id` — account ID
- `date_from` / `date_to` — date range (max 92 days)
- `limit` / `offset` — pagination

**Error Format:** `{"detail":"...","error":{"code":"...","message":"..."}}`

### Admin Endpoints

Requires `X-API-Key` header.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/admin/watermarks` | Current watermarks (incremental collection cursors) |
| `POST` | `/api/v1/admin/backfill` | Trigger data backfill |
| `POST` | `/api/v1/admin/transforms/recent` | Run transforms for recent period |
| `POST` | `/api/v1/admin/transforms/backfill` | Backfill transforms |
| `POST` | `/api/v1/admin/marts/recent` | Rebuild marts for recent period |
| `POST` | `/api/v1/admin/marts/backfill` | Backfill marts |
| `POST` | `/api/v1/admin/maintenance/run-automation` | Run automation rules |
| `POST` | `/api/v1/admin/maintenance/prune-raw` | Prune old raw data |
| `GET` | `/api/v1/admin/task-runs` | Task run audit log |

---

## ⚙️ Configuration

### Required Environment Variables

| Variable | Description |
|---|---|
| `BOOTSTRAP_CH_ADMIN_USER` | ClickHouse admin user (for migrations) |
| `BOOTSTRAP_CH_ADMIN_PASSWORD` | ClickHouse admin password |
| `CH_USER` | ClickHouse application user |
| `CH_PASSWORD` | ClickHouse application password |
| `ADMIN_API_KEY` | Admin API key (generate: `openssl rand -hex 32`) |
| `WB_TOKEN_STATISTICS` | WB statistics API token |
| `WB_TOKEN_ANALYTICS` | WB analytics API token |
| `OZON_CLIENT_ID` | Ozon client ID |
| `OZON_API_KEY` | Ozon API key |

### Optional Variables

| Variable | Description | Default |
|---|---|---|
| `OZON_PERF_API_KEY` | Ozon Performance API key (for ads) | — |
| `TG_BOT_TOKEN` | Telegram bot token for alerts | — |
| `TG_CHAT_ID` | Telegram chat ID for alerts | — |
| `CH_RO_USER` / `CH_RO_PASSWORD` | Read-only ClickHouse user for Metabase | — |
| `CH_HTTP_HOST_PORT` | ClickHouse HTTP host port | `18123` |
| `BACKEND_HOST_PORT` | Backend HTTP host port | `18080` |
| `BACKEND_TLS_HOST_PORT` | Backend HTTPS host port | `18443` |
| `METABASE_HOST_PORT` | Metabase host port | `13000` |
| `STACK_NAME` | Docker Compose stack name | `bormostats` |

### Default Ports

| Service | Port | Scope |
|---|---|---|
| Backend HTTP (nginx) | `18080` | Public |
| Backend HTTPS (nginx) | `18443` | Public |
| Metabase | `13000` | Loopback |
| ClickHouse HTTP | `18123` | Loopback |
| Worker metrics | `19101` | Loopback |
| Beat metrics | `19102` | Loopback |

> 💡 Change port mappings in `.env` if they conflict with existing services.

---

## 🛡️ Security

### Runtime Hardening

- All application containers run as non-root user (`app`, uid/gid `10001`)
- `read_only: true` — container filesystems are read-only
- `no-new-privileges` — privilege escalation disabled
- `tmpfs` for `/tmp` — writable temp storage only
- Public entry point is **only** nginx reverse proxy; backend is never exposed directly
- Loopback-only ports (ClickHouse, Metabase, metrics) on isolated `ops` network
- Redis runs on a private Docker network with no published ports

### Least Privilege Principle

- Admin API restricted to a typed allowlist of endpoints
- Admin key in web UI stored in session memory (tab-scoped)
- ClickHouse application uses a dedicated user (not bootstrap admin)
- Worker and beat isolated from public network
- Optional read-only ClickHouse user for Metabase

### Credential Rotation

Detailed instructions in `docs/credential_rotation.md`:
- WB tokens (expire after 180 days)
- Ozon Client ID / API Key
- Admin API Key
- ClickHouse credentials
- Telegram secrets

### Vulnerability Reporting

Please do **not** file public issues for security vulnerabilities. Use [GitHub Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) or contact maintainers directly. See `SECURITY.md` for details.

---

## 🧪 Testing

```bash
# Run all tests
make test

# Full check suite (lint + format + typecheck + test)
make check

# Load smoke test
make perf-smoke

# Validate Docker Compose config
make docker-config
```

### Test Structure

- `tests/unit/` — Unit tests (parsers, validation, business logic)
- `tests/integration/` — Integration tests (admin API, full scenarios)
- `tests/fixtures/` — JSON fixtures (e.g., `ozon_cancelled_posting.json`)

Current coverage: **64 tests** (54 unit + 10 integration).

---

## 📂 Repository Structure

```
BormoStats/
├── .github/                    # CI/CD, issue/PR templates, Dependabot
│   └── workflows/ci.yml        # 4-job GitHub Actions pipeline
│
├── backend/                    # FastAPI + Uvicorn
│   ├── app/
│   │   ├── main.py             # Entry point: routers, health, metrics
│   │   ├── api/v1/             # REST API routes (sales, stocks, funnel, ads, kpis, admin)
│   │   ├── core/               # Config, deps, logging, rate limiting
│   │   ├── db/                 # ClickHouse client + SQL queries
│   │   ├── models/             # Pydantic request/response models
│   │   ├── services/           # Business logic (MetricsService, AdminService)
│   │   └── ui/                 # Embedded web UI (built SPA)
│   └── Dockerfile              # Multi-stage build (Node → Python)
│
├── workers/                    # Celery workers
│   ├── app/
│   │   ├── celery_app.py       # Celery application config
│   │   ├── beat_schedule.py    # Periodic task schedule
│   │   ├── tasks/              # wb_collect, ozon_collect, transforms, marts, maintenance
│   │   ├── sql/                # SQL transforms and mart definitions
│   │   └── utils/              # Locking, watermarks, metrics, data quality
│   └── Dockerfile
│
├── frontend/                   # React 19 SPA
│   ├── src/                    # Components, pages, utilities
│   ├── vite.config.js
│   └── package.json
│
├── collectors/                 # Marketplace API clients
│   ├── wb/                     # Wildberries: client, endpoints, parsers
│   ├── ozon/                   # Ozon: client, endpoints, parsers, error handling
│   └── common/                 # HTTP client, retry, circuit breaker, redaction
│
├── warehouse/                  # ClickHouse schema and migrations
│   ├── migrations/             # Sequential SQL migrations (0001–0011)
│   ├── apply_migrations.py
│   └── ddl/                    # Reference DDL
│
├── infra/                      # Infrastructure
│   ├── docker/                 # Docker Compose, ClickHouse, Nginx config
│   ├── monitoring/             # Prometheus config + alert rules
│   └── nginx/                  # Reverse proxy config + TLS certs
│
├── automation/                 # YAML automation rules engine
│   ├── engine.py               # AST-based rule evaluator (no exec/eval)
│   ├── actions/                # Telegram action executor
│   └── rules/                  # bad_acos, low_stock, no_sales_7d
│
├── scripts/                    # Operator utilities
│   ├── bootstrap.sh            # Full stack initialization
│   ├── run_local.sh            # One-command Docker launcher
│   ├── backfill.py             # Manual data backfill
│   └── provision_clickhouse_users.py
│
├── tests/                      # Test suite (64 tests)
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   └── fixtures/               # JSON API fixtures
│
├── docs/                       # Operational documentation
│   ├── architecture.md         # Architecture and data flows
│   ├── environments.md         # Dev/stage/prod model
│   ├── observability.md        # Metrics, alerts, Grafana
│   ├── disaster_recovery.md    # Backups, RPO/RTO
│   ├── credential_rotation.md  # Secret rotation procedures
│   ├── troubleshooting.md      # Problem diagnosis
│   ├── runbooks.md             # Operator procedures
│   └── ...                     # Release management, migration policy, etc.
│
├── screenshots/                # UI screenshots for README
├── .github/                    # CI/CD workflows
├── Makefile                    # Root Makefile
├── pyproject.toml              # Python project config
├── requirements.txt            # Pinned production dependencies
├── requirements-dev.txt        # Development dependencies
├── .env.example                # Environment template
├── docker-compose.yml          # Full stack definition
├── README.md                   # English (default)
├── README.ru.md                # Русская версия
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
└── LICENSE
```

---

## 📖 Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | System architecture and data flows |
| [Environments](docs/environments.md) | Dev/stage/prod environment model |
| [Observability](docs/observability.md) | Prometheus metrics, Grafana, alerts |
| [Disaster Recovery](docs/disaster_recovery.md) | Backups, RPO/RTO, recovery procedures |
| [Credential Rotation](docs/credential_rotation.md) | Secret rotation procedures |
| [Migration Policy](docs/migration_policy.md) | Database migration policy |
| [Performance](docs/performance.md) | Performance targets and benchmarks |
| [Runbooks](docs/runbooks.md) | Operator runbooks |
| [Troubleshooting](docs/troubleshooting.md) | Problem diagnosis guide |
| [Release Management](docs/release_management.md) | Versioning and deployment |
| [Supply Chain Security](docs/supply_chain_security.md) | Dependency security and SBOM |

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

### Quick Start for Contributors

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# Set at minimum WB_STATISTICS_API_KEY and OZON_* keys
```

### Before Submitting a PR

```bash
make lint           # Ruff linting
make format-check   # Ruff format check
make typecheck      # MyPy strict typing
make test           # pytest (64 tests)
```

### Dependency Policy

- `requirements.txt` and `requirements-dev.txt` are **fully pinned** versions
- Docker images in Docker Compose are **pinned by digest**
- Dependency updates require a clean virtualenv and full test suite run
- CI runs pip-audit, Docker image scanning, and SBOM generation on every push
- Dependabot automatically creates PRs for dependency updates weekly

---

## 📜 License

[MIT](LICENSE) — feel free to use, modify, and distribute.

---

<div align="center">

**Built with ❤️ for marketplace sellers who value their data privacy.**

[![GitHub stars](https://img.shields.io/github/stars/Bormotoon/BormoStats?style=social)](https://github.com/Bormotoon/BormoStats)
[![GitHub issues](https://img.shields.io/github/issues/Bormotoon/BormoStats?style=social)](https://github.com/Bormotoon/BormoStats/issues)

</div>
