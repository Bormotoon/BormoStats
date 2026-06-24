.PHONY: help up down logs ps migrate bootstrap lint format format-check typecheck test check check-tokens perf-smoke docker-config frontend install run run-backend run-worker run-beat install-systemd

STACK_NAME ?= bormostats
COMPOSE_CMD = docker compose --project-name $(STACK_NAME) --env-file .env -f infra/docker/docker-compose.yml
VENV_BIN := .venv/bin
PYTHON_BIN := $(if $(wildcard $(VENV_BIN)/python),$(VENV_BIN)/python,python3)
RUFF_BIN := $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
MYPY_BIN := $(if $(wildcard $(VENV_BIN)/mypy),$(VENV_BIN)/mypy,mypy)
PYTEST_BIN := $(if $(wildcard $(VENV_BIN)/pytest),$(VENV_BIN)/pytest,pytest)

help:
	@echo "BormoStats — Marketplace Analytics v1.0.0"
	@echo ""
	@echo "=== Docker (recommended) ==="
	@echo "  make up           Build and start all Docker services"
	@echo "  make down         Stop all Docker services"
	@echo "  make logs         Tail Docker logs"
	@echo "  make ps           Container status"
	@echo ""
	@echo "=== OS (bare metal) ==="
	@echo "  make install      Install Python deps, build frontend, apply migrations"
	@echo "  make run          Start all services in foreground"
	@echo "  make run-backend  Start backend only"
	@echo "  make run-worker   Start Celery worker only"
	@echo "  make run-beat     Start Celery beat only"
	@echo "  make install-systemd  Install systemd service files"
	@echo ""
	@echo "=== Development ==="
	@echo "  make frontend     Build React frontend"
	@echo "  make migrate      Apply ClickHouse migrations"
	@echo "  make bootstrap    Full stack init (after .env is ready)"
	@echo "  make lint         Ruff check"
	@echo "  make format       Ruff format"
	@echo "  make format-check Ruff format check"
	@echo "  make typecheck    MyPy strict"
	@echo "  make test         Pytest"
	@echo "  make check        Run all checks (lint + format + typecheck + test)"
	@echo ""
	@echo "=== Operations ==="
	@echo "  make check-tokens  Validate WB/Ozon API tokens"
	@echo "  make perf-smoke    Load smoke test"

up:
	bash scripts/run_local.sh

down:
	$(COMPOSE_CMD) down

logs:
	$(COMPOSE_CMD) logs -f --tail=200

ps:
	$(COMPOSE_CMD) ps

migrate:
	$(PYTHON_BIN) warehouse/apply_migrations.py

bootstrap:
	./scripts/bootstrap.sh

lint:
	$(RUFF_BIN) check .

format:
	$(RUFF_BIN) format .

format-check:
	$(RUFF_BIN) format --check .

typecheck:
	$(MYPY_BIN) backend workers collectors automation warehouse scripts common

test:
	$(PYTEST_BIN) -q

check:
	$(RUFF_BIN) check .
	$(RUFF_BIN) format --check .
	$(MYPY_BIN) backend workers collectors automation warehouse scripts common
	$(PYTEST_BIN) -q

check-tokens:
	$(PYTHON_BIN) scripts/check_tokens.py

perf-smoke:
	$(PYTHON_BIN) scripts/perf_smoke.py

docker-config:
	$(COMPOSE_CMD) config -q

frontend:
	cd frontend && npm ci && npm run build
	rm -rf ../backend/app/ui/dist 2>/dev/null || true
	cp -r frontend/dist backend/app/ui/dist
	cp frontend/favicon.svg backend/app/ui/dist/ 2>/dev/null || true
	@echo "Frontend built -> backend/app/ui/dist/"

# === OS (bare metal) targets ===

install:
	bash scripts/install.sh

run:
	bash scripts/run_os.sh

run-backend:
	@echo "Starting backend..."
	PYTHONPATH="backend:." $(PYTHON_BIN) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

run-worker:
	@echo "Starting Celery worker..."
	PYTHONPATH="workers:." CELERY_METRICS_ROLE=worker CELERY_METRICS_PORT=9101 $(PYTHON_BIN) -m celery -A app.celery_app:celery_app worker --loglevel=INFO --concurrency=4

run-beat:
	@echo "Starting Celery beat..."
	PYTHONPATH="workers:." CELERY_METRICS_ROLE=beat CELERY_METRICS_PORT=9102 $(PYTHON_BIN) -m celery -A app.celery_app:celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule

install-systemd:
	@echo "Installing systemd service files..."
	@echo "  sudo cp infra/systemd/bormostats-*.service /etc/systemd/system/"
	@echo "  sudo systemctl daemon-reload"
	@echo "  sudo systemctl enable --now bormostats-backend bormostats-worker bormostats-beat"
	@echo ""
	@echo "Note: These services expect the app at /opt/bormostats/"
	@echo "Edit infra/systemd/*.service to change paths if needed."
