from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("CH_USER", "analytics_app")
os.environ.setdefault("CH_PASSWORD", "super-secret-clickhouse-password")
os.environ.setdefault("CH_HOST", "localhost")
os.environ.setdefault("CH_PORT", "8123")
os.environ.setdefault("CH_DB", "mp_analytics")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import app.api.v1.admin as admin_api  # noqa: E402
import app.services.admin_service as admin_service_module  # noqa: E402
from app.core.deps import get_ch_client  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import (  # noqa: E402
    AdminRequestContext,
    BackfillRequest,
    TransformBackfillRequest,
)
from app.services.admin_service import AdminService  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_ch_client] = lambda: object()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_run_task_endpoint_removed(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/run-task",
        headers={"X-API-Key": "test-admin-key"},
        json={"task_name": "tasks.transforms.transform_all_recent", "args": [], "kwargs": {}},
    )

    assert response.status_code == 404


def test_backfill_request_rejects_invalid_marketplace_dataset_combo() -> None:
    with pytest.raises(ValidationError):
        BackfillRequest(marketplace="wb", dataset="finance", days=14)

    with pytest.raises(ValidationError):
        BackfillRequest(marketplace="wb", dataset="sales", days=365)


def test_transform_backfill_endpoint_queues_whitelisted_action(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str]] = []

    class FakeAdminService:
        def __init__(self, client: object, settings: object) -> None:
            self.client = client
            self.settings = settings

        def queue_transform_backfill(
            self,
            payload: TransformBackfillRequest,
            audit: AdminRequestContext,
        ) -> dict[str, object]:
            calls.append((payload.days, audit.remote_addr))
            return {
                "action": "transform_backfill",
                "task_name": "tasks.transforms.transform_backfill_days",
                "task_id": "task-123",
                "queued_at": "2026-03-06T00:00:00+00:00",
                "parameters": {"days": payload.days},
            }

    monkeypatch.setattr(admin_api, "AdminService", FakeAdminService)

    response = client.post(
        "/api/v1/admin/transforms/backfill",
        headers={"X-API-Key": "test-admin-key"},
        json={"days": 30},
    )

    assert response.status_code == 200
    assert response.json()["task_name"] == "tasks.transforms.transform_backfill_days"
    assert calls == [(30, "testclient")]


def test_admin_service_logs_queued_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_tasks: list[tuple[str, list[int], dict[str, object]]] = []
    audit_entries: list[tuple[str, dict[str, object]]] = []

    class FakeAsyncResult:
        id = "queued-task-1"

    class FakeCelery:
        def send_task(
            self,
            task_name: str,
            args: list[int] | None = None,
            kwargs: dict[str, object] | None = None,
        ) -> FakeAsyncResult:
            sent_tasks.append((task_name, args or [], kwargs or {}))
            return FakeAsyncResult()

    class FakeLogger:
        def info(self, event: str, **kwargs: object) -> None:
            audit_entries.append((event, dict(kwargs)))

    service = AdminService(client=None, settings=SimpleNamespace(redis_url="redis://localhost:6379/0"))  # type: ignore[arg-type]
    service.celery = FakeCelery()  # type: ignore[assignment]
    monkeypatch.setattr(admin_service_module, "LOGGER", FakeLogger())

    response = service.queue_backfill(
        BackfillRequest(marketplace="wb", dataset="sales", days=14),
        audit=AdminRequestContext(
            path="/api/v1/admin/backfill",
            method="POST",
            remote_addr="127.0.0.1",
            forwarded_for=None,
            user_agent="pytest",
        ),
    )

    assert response.task_name == "tasks.wb_collect.wb_sales_backfill_days"
    assert sent_tasks == [("tasks.wb_collect.wb_sales_backfill_days", [14], {})]
    assert audit_entries[0][0] == "admin_action_queued"
    assert audit_entries[0][1]["action"] == "backfill"
    assert audit_entries[0][1]["details"]["parameters"] == {
        "marketplace": "wb",
        "dataset": "sales",
        "days": 14,
    }
