from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKERS_DIR = ROOT_DIR / "workers"
CELERY_APP_PATH = WORKERS_DIR / "app" / "celery_app.py"


def _load_worker_celery_module() -> Any:
    env_defaults = {
        "CH_USER": "analytics_app",
        "CH_PASSWORD": "super-secret-clickhouse-password",
        "CH_HOST": "localhost",
        "CH_PORT": "8123",
        "CH_DB": "mp_analytics",
        "REDIS_URL": "redis://localhost:6379/0",
        "WB_TOKEN_STATISTICS": "wb-stat-token",
        "WB_TOKEN_ANALYTICS": "wb-analytics-token",
        "OZON_CLIENT_ID": "ozon-client-id",
        "OZON_API_KEY": "ozon-api-key",
    }
    for key, value in env_defaults.items():
        os.environ.setdefault(key, value)

    if str(WORKERS_DIR) not in sys.path:
        sys.path.insert(0, str(WORKERS_DIR))
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

    spec = importlib.util.spec_from_file_location(
        "worker_celery_config_test",
        CELERY_APP_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_celery_uses_redis_as_broker_only() -> None:
    celery_module = _load_worker_celery_module()

    assert celery_module.celery_app.conf.broker_url == "redis://localhost:6379/0"
    assert celery_module.celery_app.conf.task_ignore_result is True
    assert celery_module.celery_app.conf.result_backend is None
    assert type(celery_module.celery_app.backend).__name__ == "DisabledBackend"
