"""Shared test configuration: deterministic environment for backend/worker imports."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
# Backend and workers both ship an ``app`` package, so they cannot share one
# interpreter. The worker suite (tests/worker_suite) runs in a subprocess started
# by tests/unit/test_worker_suite.py with BORMOSTATS_TEST_TARGET=workers.
TARGET = os.environ.get("BORMOSTATS_TEST_TARGET", "backend")
for path in (ROOT_DIR / TARGET, ROOT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

collect_ignore = ["worker_suite"] if TARGET == "backend" else []

_DEFAULTS = {
    "APP_ENV": "dev",
    "ADMIN_API_KEY": "test-admin-key",
    "CH_USER": "analytics_app",
    "CH_PASSWORD": "super-secret-clickhouse-password",
    "CH_HOST": "localhost",
    "CH_PORT": "8123",
    "CH_DB": "mp_analytics",
    "REDIS_URL": "redis://localhost:6379/0",
    "WEBHOOK_SECRET_KEY": "test-webhook-secret-key",
    # No background dependency polling while tests run.
    "METRICS_REFRESH_SECONDS": "0",
    "AUTH_CACHE_TTL_SECONDS": "0",
    "WB_TOKEN_STATISTICS": "test-wb-statistics-token",
    "WB_TOKEN_ANALYTICS": "test-wb-analytics-token",
    "OZON_CLIENT_ID": "test-ozon-client-id",
    "OZON_API_KEY": "test-ozon-api-key",
    # Explicit values so a developer's local .env (read by pydantic-settings) cannot leak in.
    "REDIS_USERNAME": "",
    "REDIS_PASSWORD": "",
    "ADMIN_ALLOWED_NETWORKS": "",
    "PUBLIC_READ_API": "false",
    "METRICS_BEARER_TOKEN": "",
    "WEBHOOK_ALLOW_PRIVATE_TARGETS": "false",
    "MARKETPLACE_ACTIONS_ENABLED": "false",
}
for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)

# Route-inventory tests issue hundreds of requests from one client.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000/minute")
os.environ.setdefault("ADMIN_RATE_LIMIT_PER_MINUTE", "100000/minute")
