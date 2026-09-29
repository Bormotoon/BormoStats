from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.core.auth import ROLE_SCOPES, AuthContext, AuthMethod
from app.core.deps import get_ch_client
from app.main import app
from app.models.organization import OrgMemberRole
from fastapi.testclient import TestClient

from common.exports import export_path
from tests.fakes import FakeClickHouse

JOB = {
    "export_id": "11111111-2222-3333-4444-555555555555",
    "organization_id": "org-a",
    "requested_by": "u-1",
    "dataset": "sales_daily",
    "params_json": "{}",
    "status": "done",
    "row_count": 2,
    "file_name": "x.csv",
    "error": "",
    "created_at": datetime(2026, 9, 1, tzinfo=UTC),
    "updated_at": datetime(2026, 9, 1, tzinfo=UTC),
}


@pytest.fixture
def ch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeClickHouse]:
    import app.core.auth as auth_module

    monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
    ctx = AuthContext(
        principal_id="u-1",
        organization_id="org-a",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    monkeypatch.setattr(auth_module, "resolve_auth_context", lambda *a, **k: ctx)
    fake = FakeClickHouse()
    app.dependency_overrides[get_ch_client] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def _client() -> TestClient:
    return TestClient(app, headers={"X-API-Key": "k"})


def test_create_export_queues_task_for_caller_org(
    ch: FakeClickHouse, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.services.export_service.send_task",
        lambda settings, name, **kw: sent.append({"name": name, **kw}) or "t",
    )
    response = _client().post(
        "/api/v1/exports", json={"dataset": "sales_daily", "account_id": "shop-1"}
    )
    assert response.status_code == 202
    assert response.json()["organization_id"] == "org-a"
    assert sent[0]["name"] == "tasks.exports.run_export"
    assert sent[0]["kwargs"]["organization_id"] == "org-a"
    ((_, params),) = ch.commands_matching("INSERT INTO sys_export_jobs")
    assert params["status"] == "queued" and "shop-1" in params["params_json"]


def test_unknown_dataset_is_rejected(ch: FakeClickHouse) -> None:
    assert _client().post("/api/v1/exports", json={"dataset": "dim_user"}).status_code == 422


def test_download_serves_file_of_own_org_only(ch: FakeClickHouse) -> None:
    path = export_path("org-a", JOB["export_id"])
    path.parent.mkdir(parents=True)
    path.write_text("day,marketplace\n", encoding="utf-8")
    ch.on("FROM sys_export_jobs", [JOB])
    response = _client().get(f"/api/v1/exports/{JOB['export_id']}/download")
    assert response.status_code == 200
    assert response.text.startswith("day,marketplace")
    _, params = ch.queries[-1]
    assert params["oid"] == "org-a"


def test_download_before_completion_is_conflict(ch: FakeClickHouse) -> None:
    ch.on("FROM sys_export_jobs", [{**JOB, "status": "running"}])
    response = _client().get(f"/api/v1/exports/{JOB['export_id']}/download")
    assert response.status_code == 409


def test_export_path_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        export_path("org-a", "../../etc/passwd")
