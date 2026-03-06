from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
WORKERS_DIR = ROOT_DIR / "workers"
WORKER_RUNTIME_PATH = WORKERS_DIR / "app" / "utils" / "runtime.py"
WORKER_MAINTENANCE_PATH = WORKERS_DIR / "app" / "tasks" / "maintenance.py"

for path in (BACKEND_DIR, WORKERS_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("CH_USER", "analytics_app")
os.environ.setdefault("CH_PASSWORD", "super-secret-clickhouse-password")
os.environ.setdefault("CH_HOST", "localhost")
os.environ.setdefault("CH_PORT", "8123")
os.environ.setdefault("CH_DB", "mp_analytics")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import app.core.deps as backend_deps  # noqa: E402
import app.db.ch as backend_ch  # noqa: E402


def _load_worker_module(module_name: str, path: Path) -> Any:
    if str(WORKERS_DIR) not in sys.path:
        sys.path.insert(0, str(WORKERS_DIR))
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backend_cached_client_disables_session_autogeneration(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_client(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return object()

    backend_deps._get_cached_ch_client.cache_clear()
    monkeypatch.setattr(backend_deps.clickhouse_connect, "get_client", fake_get_client)

    backend_deps._get_cached_ch_client("localhost", 8123, "analytics_app", "secret", "mp_analytics")

    assert calls == [
        {
            "host": "localhost",
            "port": 8123,
            "username": "analytics_app",
            "password": "secret",
            "database": "mp_analytics",
            "autogenerate_session_id": False,
        }
    ]


def test_build_client_disables_session_autogeneration(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_client(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return object()

    monkeypatch.setattr(backend_ch.clickhouse_connect, "get_client", fake_get_client)
    settings = type(
        "SettingsStub",
        (),
        {
            "ch_host": "localhost",
            "ch_port": 8123,
            "ch_user": "analytics_app",
            "ch_password": "secret",
            "ch_db": "mp_analytics",
        },
    )()

    backend_ch.build_client(settings)

    assert calls[0]["autogenerate_session_id"] is False


def test_worker_cached_client_disables_session_autogeneration(monkeypatch) -> None:
    worker_runtime = _load_worker_module("worker_runtime_config_test", WORKER_RUNTIME_PATH)
    calls: list[dict[str, object]] = []

    def fake_get_client(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return object()

    worker_runtime.get_ch_client.cache_clear()
    monkeypatch.setattr(worker_runtime.clickhouse_connect, "get_client", fake_get_client)

    worker_runtime.get_ch_client()

    assert calls[0]["autogenerate_session_id"] is False


def test_maintenance_client_disables_session_autogeneration(monkeypatch) -> None:
    maintenance_tasks = _load_worker_module(
        "worker_maintenance_client_test",
        WORKER_MAINTENANCE_PATH,
    )
    calls: list[dict[str, object]] = []

    def fake_get_client(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return object()

    monkeypatch.setattr(maintenance_tasks.clickhouse_connect, "get_client", fake_get_client)

    maintenance_tasks._ch_client()

    assert calls[0]["autogenerate_session_id"] is False
