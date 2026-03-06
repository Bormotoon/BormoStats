from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
WORKERS_DIR = ROOT_DIR / "workers"


def _run_import(
    module: str,
    cwd: Path,
    pythonpath: str,
    overrides: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        **overrides,
    }
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_backend_import_fails_with_placeholder_admin_key() -> None:
    result = _run_import(
        "app.main",
        BACKEND_DIR,
        os.pathsep.join([str(BACKEND_DIR), str(ROOT_DIR)]),
        {
            "ADMIN_API_KEY": "change_me",
            "CH_USER": "analytics_app",
            "CH_PASSWORD": "super-secret-clickhouse-password",
            "CH_DB": "mp_analytics",
            "CH_HOST": "localhost",
            "CH_PORT": "8123",
            "REDIS_URL": "redis://localhost:6379/0",
        },
    )

    assert result.returncode != 0
    assert "ADMIN_API_KEY" in f"{result.stdout}\n{result.stderr}"


def test_worker_import_fails_with_placeholder_marketplace_credentials() -> None:
    result = _run_import(
        "app.celery_app",
        WORKERS_DIR,
        os.pathsep.join([str(WORKERS_DIR), str(ROOT_DIR)]),
        {
            "CH_USER": "analytics_app",
            "CH_PASSWORD": "super-secret-clickhouse-password",
            "CH_DB": "mp_analytics",
            "CH_HOST": "localhost",
            "CH_PORT": "8123",
            "REDIS_URL": "redis://localhost:6379/0",
            "WB_TOKEN_STATISTICS": "",
            "WB_TOKEN_ANALYTICS": "real-wb-analytics-token",
            "OZON_CLIENT_ID": "real-ozon-client-id",
            "OZON_API_KEY": "real-ozon-api-key",
        },
    )

    assert result.returncode != 0
    assert "WB_TOKEN_STATISTICS" in f"{result.stdout}\n{result.stderr}"


def test_check_tokens_rejects_placeholder_clickhouse_password() -> None:
    env = {
        **os.environ,
        "CH_USER": "analytics_app",
        "CH_PASSWORD": "replace-with-strong-clickhouse-password",
        "ADMIN_API_KEY": "real-admin-key",
        "WB_TOKEN_STATISTICS": "real-wb-statistics-token",
        "WB_TOKEN_ANALYTICS": "real-wb-analytics-token",
        "OZON_CLIENT_ID": "real-ozon-client-id",
        "OZON_API_KEY": "real-ozon-api-key",
    }
    result = subprocess.run(
        [sys.executable, "scripts/check_tokens.py", "--skip-api"],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "CH_PASSWORD" in f"{result.stdout}\n{result.stderr}"
