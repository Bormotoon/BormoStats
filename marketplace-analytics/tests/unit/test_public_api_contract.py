from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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

import app.api.v1.sales as sales_api  # noqa: E402
from app.core.deps import get_ch_client  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_ch_client] = lambda: object()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_public_endpoint_rejects_invalid_marketplace_with_standard_error(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/sales/daily", params={"marketplace": "amazon"})

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "validation failed"
    assert payload["error"]["code"] == "validation_error"
    assert any(item["loc"] == "query.marketplace" for item in payload["error"]["details"])


def test_public_endpoint_rejects_too_wide_date_window(client: TestClient) -> None:
    response = client.get(
        "/api/v1/sales/daily",
        params={"date_from": "2025-01-01", "date_to": "2025-04-10"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "date window must not exceed 92 days",
        "error": {
            "code": "validation_error",
            "message": "date window must not exceed 92 days",
            "details": [],
        },
    }


def test_public_endpoint_adds_pagination_and_passes_offset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeMetricsService:
        def __init__(self, client: object) -> None:
            self.client = client

        def sales_daily(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(dict(kwargs))
            return [
                {"day": "2026-03-01", "product_id": "sku-2"},
                {"day": "2026-03-02", "product_id": "sku-3"},
            ]

    monkeypatch.setattr(sales_api, "MetricsService", FakeMetricsService)

    response = client.get("/api/v1/sales/daily", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    assert response.json()["items"] == [{"day": "2026-03-01", "product_id": "sku-2"}]
    assert response.json()["pagination"] == {
        "limit": 1,
        "offset": 1,
        "returned": 1,
        "next_offset": 2,
        "has_more": True,
    }
    assert len(calls) == 1
    assert calls[0]["date_from"].isoformat() == response.json()["from"]
    assert calls[0]["date_to"].isoformat() == response.json()["to"]
    assert calls[0]["marketplace"] == ""
    assert calls[0]["account_id"] == ""
    assert calls[0]["limit"] == 2
    assert calls[0]["offset"] == 1


def test_public_endpoint_sanitizes_unhandled_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingMetricsService:
        def __init__(self, client: object) -> None:
            self.client = client

        def sales_daily(self, **kwargs: object) -> list[dict[str, object]]:
            raise RuntimeError("db=mp_analytics redis=redis://secret@redis:6379/0")

    monkeypatch.setattr(sales_api, "MetricsService", ExplodingMetricsService)
    app.dependency_overrides[get_ch_client] = lambda: object()
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/api/v1/sales/daily")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {
        "detail": "internal server error",
        "error": {
            "code": "internal_error",
            "message": "internal server error",
            "details": [],
        },
    }
    assert "secret@redis" not in response.text
