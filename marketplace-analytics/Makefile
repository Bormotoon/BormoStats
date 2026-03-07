.PHONY: help up down logs ps migrate bootstrap lint format black-check typecheck test check-tokens perf-smoke docker-config

STACK_NAME ?= bormostats
COMPOSE_CMD = docker compose --project-name $(STACK_NAME) --env-file .env -f infra/docker/docker-compose.yml
VENV_BIN := .venv/bin
PYTHON_BIN := $(if $(wildcard $(VENV_BIN)/python),$(VENV_BIN)/python,python3)
RUFF_BIN := $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
BLACK_BIN := $(if $(wildcard $(VENV_BIN)/black),$(VENV_BIN)/black,black)
MYPY_BIN := $(if $(wildcard $(VENV_BIN)/mypy),$(VENV_BIN)/mypy,mypy)
PYTEST_BIN := $(if $(wildcard $(VENV_BIN)/pytest),$(VENV_BIN)/pytest,pytest)

help:
	@echo "Targets: up down logs ps migrate bootstrap lint format black-check typecheck test check-tokens perf-smoke docker-config"
	@echo "Variables: STACK_NAME=$(STACK_NAME)"

up:
	$(COMPOSE_CMD) up -d --build

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
	$(BLACK_BIN) .

black-check:
	$(BLACK_BIN) --check .

typecheck:
	$(MYPY_BIN) backend workers collectors automation warehouse scripts

test:
	$(PYTEST_BIN) -q

check-tokens:
	$(PYTHON_BIN) scripts/check_tokens.py

perf-smoke:
	$(PYTHON_BIN) scripts/perf_smoke.py

docker-config:
	$(COMPOSE_CMD) config -q
