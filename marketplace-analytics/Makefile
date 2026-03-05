.PHONY: help up down logs ps migrate bootstrap lint format typecheck test check-tokens

STACK_NAME ?= bormostats
COMPOSE_CMD = docker compose --project-name $(STACK_NAME) --env-file .env -f infra/docker/docker-compose.yml

help:
	@echo "Targets: up down logs ps migrate bootstrap lint format typecheck test check-tokens"
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
	python3 warehouse/apply_migrations.py

bootstrap:
	./scripts/bootstrap.sh

lint:
	ruff check .

format:
	black .

typecheck:
	mypy backend workers collectors automation warehouse scripts

test:
	pytest -q

check-tokens:
	python3 scripts/check_tokens.py
