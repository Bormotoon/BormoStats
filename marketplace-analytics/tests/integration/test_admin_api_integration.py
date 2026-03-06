from __future__ import annotations

from fastapi.testclient import TestClient


def test_admin_backfill_routes_live_message_to_expected_queue(
    integration_runtime,
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/v1/admin/backfill",
        headers={"X-API-Key": integration_runtime.admin_api_key},
        json={"marketplace": "wb", "dataset": "sales", "days": 14},
    )

    assert response.status_code == 200
    assert response.json()["task_name"] == "tasks.wb_collect.wb_sales_backfill_days"

    redis_client = integration_runtime.redis_client()
    try:
        assert redis_client.llen("wb") == 1
        assert redis_client.llen("celery") == 0
    finally:
        redis_client.close()


def test_admin_backfill_rejects_invalid_whitelist_combo_live(
    integration_runtime,
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/api/v1/admin/backfill",
        headers={"X-API-Key": integration_runtime.admin_api_key},
        json={"marketplace": "wb", "dataset": "finance", "days": 14},
    )

    assert response.status_code == 422

    redis_client = integration_runtime.redis_client()
    try:
        assert redis_client.dbsize() == 0
    finally:
        redis_client.close()
