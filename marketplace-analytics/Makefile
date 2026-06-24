.PHONY: help up down logs ps migrate bootstrap lint format format-check typecheck test check-tokens perf-smoke docker-config frontend

STACK_NAME ?= bormostats
COMPOSE_CMD = docker compose --project-name $(STACK_NAME) --env-file .env -f infra/docker/docker-compose.yml
VENV_BIN := .venv/bin
PYTHON_BIN := $(if $(wildcard $(VENV_BIN)/python),$(VENV_BIN)/python,python3)
RUFF_BIN := $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
MYPY_BIN := $(if $(wildcard $(VENV_BIN)/mypy),$(VENV_BIN)/mypy,mypy)
PYTEST_BIN := $(if $(wildcard $(VENV_BIN)/pytest),$(VENV_BIN)/pytest,pytest)

help:
	@echo "BormoStats — Marketplace Analytics"
	@echo ""
	@echo "Quick start:"
	@echo "  make up           Build and start all services"
	@echo ""
	@echo "Management:"
	@echo "  make down         Stop all services"
	@echo "  make logs         Tail logs"
	@echo "  make ps           Container status"
	@echo "  make migrate      Apply ClickHouse migrations"
	@echo "  make bootstrap    Full stack init (after .env is ready)"
	@echo ""
	@echo "Development:"
	@echo "  make frontend     Build React frontend"
	@echo "  make lint         Ruff check"
	@echo "  make format       Ruff format"
	@echo "  make typecheck    MyPy strict"
	@echo "  make test         Pytest"
	@echo ""
	@echo "Variables: STACK_NAME=$(STACK_NAME)"

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

check-tokens:
	$(PYTHON_BIN) scripts/check_tokens.py

perf-smoke:
	$(PYTHON_BIN) scripts/perf_smoke.py

docker-config:
	$(COMPOSE_CMD) config -q

frontend:
	cd frontend && npm ci && npm run build
	rm -rf ../backend/app/ui/dist
	cp -r frontend/dist ../backend/app/ui/dist
	cp frontend/favicon.svg ../backend/app/ui/dist/ 2>/dev/null || true
	@echo "Frontend built → backend/app/ui/dist/"
