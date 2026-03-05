.PHONY: help up down logs ps migrate bootstrap lint format typecheck test check-tokens

help:
	@echo "Targets: up down logs ps migrate bootstrap lint format typecheck test check-tokens"

up:
	cd infra/docker && docker compose --env-file ../../.env -f docker-compose.yml up -d --build

down:
	cd infra/docker && docker compose --env-file ../../.env -f docker-compose.yml down

logs:
	cd infra/docker && docker compose --env-file ../../.env -f docker-compose.yml logs -f --tail=200

ps:
	cd infra/docker && docker compose --env-file ../../.env -f docker-compose.yml ps

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
