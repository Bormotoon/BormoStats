.PHONY: help bootstrap lint format typecheck test check check-tokens perf-smoke docker-config up

PROJECT_DIR := marketplace-analytics

help:
	@echo "BormoStats — Marketplace Analytics"
	@echo ""
	@echo "Quick start:"
	@echo "  make up          Build and start all services (Docker)"
	@echo ""
	@echo "Development:"
	@echo "  make lint        Run ruff linter"
	@echo "  make format      Run ruff formatter"
	@echo "  make typecheck   Run mypy type checker"
	@echo "  make test        Run pytest"
	@echo "  make check       Run all checks (lint + format + typecheck + test)"
	@echo ""
	@echo "Operations:"
	@echo "  make bootstrap   Full stack initialization"
	@echo "  make check-tokens Validate WB/Ozon API tokens"
	@echo "  make perf-smoke  Load smoke test"

up:
	cd $(PROJECT_DIR) && bash scripts/run_local.sh

bootstrap:
	$(MAKE) -C $(PROJECT_DIR) bootstrap

lint:
	$(MAKE) -C $(PROJECT_DIR) lint

format:
	$(MAKE) -C $(PROJECT_DIR) format

typecheck:
	$(MAKE) -C $(PROJECT_DIR) typecheck

test:
	$(MAKE) -C $(PROJECT_DIR) test

check:
	$(MAKE) -C $(PROJECT_DIR) lint
	$(MAKE) -C $(PROJECT_DIR) black-check
	$(MAKE) -C $(PROJECT_DIR) typecheck
	$(MAKE) -C $(PROJECT_DIR) test

check-tokens:
	$(MAKE) -C $(PROJECT_DIR) check-tokens

perf-smoke:
	$(MAKE) -C $(PROJECT_DIR) perf-smoke

docker-config:
	$(MAKE) -C $(PROJECT_DIR) docker-config
