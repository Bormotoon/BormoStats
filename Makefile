.PHONY: help bootstrap lint format typecheck test check check-tokens perf-smoke docker-config

PROJECT_DIR := marketplace-analytics

help:
	@echo "Targets: bootstrap lint format typecheck test check check-tokens perf-smoke docker-config"
	@echo "Project directory: $(PROJECT_DIR)"

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
