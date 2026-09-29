from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
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


def test_backend_client_uses_timeouts_and_is_instrumented(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def query(self, *args: object, **kwargs: object) -> str:
            return "query-result"

        def command(self, *args: object, **kwargs: object) -> str:
            return "command-result"

        def insert(self, *args: object, **kwargs: object) -> str:
            return "insert-result"

    def fake_build_raw_client(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return FakeClient()

    monkeypatch.setattr(backend_deps, "build_raw_client", fake_build_raw_client)
    settings = SimpleNamespace(
        ch_host="localhost",
        ch_port=8123,
        ch_user="analytics_app",
        ch_password="secret",
        ch_db="mp_analytics",
        ch_pool_maxsize=16,
        ch_connect_timeout_seconds=5,
        ch_query_timeout_seconds=30,
    )

    client = backend_deps.create_ch_client(settings)

    assert calls == [
        {
            "host": "localhost",
            "port": 8123,
            "username": "analytics_app",
            "password": "secret",
            "database": "mp_analytics",
            "pool_maxsize": 16,
            "connect_timeout": 5,
            "query_timeout": 30,
        }
    ]
    assert client.query("SELECT 1") == "query-result"
    samples = backend_deps.CLICKHOUSE_QUERY_SECONDS.collect()[0].samples
    assert any(s.labels.get("operation") == "query" for s in samples)


def test_backend_client_lifecycle_is_owned_by_app(monkeypatch) -> None:
    closed: list[bool] = []

    class FakeClient:
        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(backend_deps, "create_ch_client", lambda settings: FakeClient())
    app = SimpleNamespace(state=SimpleNamespace())

    first = backend_deps.open_ch_client(app, object())
    assert backend_deps.open_ch_client(app, object()) is first
    backend_deps.close_ch_client(app)
    assert closed == [True]
    assert app.state.ch_client is None


def test_build_client_disables_session_autogeneration(monkeypatch) -> None:
    client_calls: list[dict[str, object]] = []
    pool_calls: list[dict[str, object]] = []

    def fake_pool_manager(**kwargs: object) -> object:
        pool_calls.append(dict(kwargs))
        return object()

    def fake_get_client(**kwargs: object) -> object:
        client_calls.append(dict(kwargs))
        return object()

    monkeypatch.setattr(backend_ch, "get_pool_manager", fake_pool_manager)
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
            "ch_pool_maxsize": 24,
            "ch_connect_timeout_seconds": 3,
            "ch_query_timeout_seconds": 20,
        },
    )()

    backend_ch.build_client(settings)

    assert pool_calls == [{"maxsize": 24}]
    assert client_calls[0]["autogenerate_session_id"] is False
    assert client_calls[0]["connect_timeout"] == 3
    assert client_calls[0]["send_receive_timeout"] == 25
    assert client_calls[0]["settings"] == {"max_execution_time": 20}
    assert client_calls[0]["pool_mgr"] is not None


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


def test_maintenance_reuses_worker_runtime_client() -> None:
    mod = _load_worker_module("worker_maintenance_test", WORKER_MAINTENANCE_PATH)
    assert not hasattr(mod, "_ch_client"), "maintenance should not define its own _ch_client"
    assert mod.get_ch_client is not None, "maintenance should use get_ch_client from runtime"
