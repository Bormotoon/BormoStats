"""Two organizations on a real ClickHouse: no cross-tenant reads or writes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _admin(api_client: TestClient, org: str) -> dict[str, str]:
    return {"X-Organization-Id": org, "X-API-Key": api_client.headers["X-API-Key"]}


def _create_org_with_account(api_client: TestClient, account_id: str) -> str:
    org = api_client.post("/api/v1/organizations", json={"name": f"Org {account_id}"})
    assert org.status_code == 201, org.text
    org_id = org.json()["organization_id"]
    acct = api_client.post(
        f"/api/v1/organizations/{org_id}/accounts",
        json={"account_id": account_id, "marketplace": "wb", "title": account_id},
    )
    assert acct.status_code == 201, acct.text
    return str(org_id)


def _create_user(api_client: TestClient, org_id: str, role: int = 2) -> dict[str, Any]:
    response = api_client.post(
        "/api/v1/users",
        headers=_admin(api_client, org_id),
        json={"name": "u", "email": f"{uuid4().hex[:6]}@example.com", "org_role": role},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["api_key"].startswith("bsk_")
    return dict(body)


@pytest.fixture
def tenants(integration_runtime: Any, api_client: TestClient) -> dict[str, Any]:
    suffix = uuid4().hex[:6]
    org_a = _create_org_with_account(api_client, f"acc-a-{suffix}")
    org_b = _create_org_with_account(api_client, f"acc-b-{suffix}")
    user_a = _create_user(api_client, org_a)
    user_b = _create_user(api_client, org_b)

    day = date.today() - timedelta(days=1)
    client = integration_runtime.ch_client()
    try:
        client.insert(
            "mrt_sales_daily",
            [
                [day, "wb", f"acc-a-{suffix}", "sku-a", 1, 100.0, 90.0, 0],
                [day, "wb", f"acc-b-{suffix}", "sku-b", 2, 200.0, 180.0, 0],
            ],
            column_names=[
                "day",
                "marketplace",
                "account_id",
                "product_id",
                "qty",
                "revenue",
                "payout",
                "returns_qty",
            ],
        )
    finally:
        client.close()
    return {
        "suffix": suffix,
        "day": day,
        "org_a": org_a,
        "org_b": org_b,
        "key_a": user_a["api_key"],
        "key_b": user_b["api_key"],
        "user_a": user_a["user_id"],
    }


def _as(key: str, **extra: str) -> dict[str, str]:
    return {"X-API-Key": key, **extra}


def test_analytics_reads_are_isolated(api_client: TestClient, tenants: dict[str, Any]) -> None:
    params = {"date_from": tenants["day"].isoformat(), "date_to": tenants["day"].isoformat()}
    rows_a = api_client.get(
        "/api/v1/sales/daily", params=params, headers=_as(tenants["key_a"])
    ).json()["items"]
    rows_b = api_client.get(
        "/api/v1/sales/daily",
        params=params,
        headers=_as(tenants["key_b"], **{"X-Organization-Id": tenants["org_a"]}),
    ).json()["items"]
    assert {r["product_id"] for r in rows_a} == {"sku-a"}
    # the org header is ignored for user keys
    assert {r["product_id"] for r in rows_b} == {"sku-b"}

    accounts_b = api_client.get("/api/v1/accounts", headers=_as(tenants["key_b"])).json()
    assert [a["account_id"] for a in accounts_b] == [f"acc-b-{tenants['suffix']}"]


def test_cross_tenant_writes_are_rejected(api_client: TestClient, tenants: dict[str, Any]) -> None:
    foreign_rule = api_client.post(
        "/api/v1/bidder/rules",
        headers=_as(tenants["key_b"]),
        json={
            "campaign_id": "1",
            "marketplace": "wb",
            "account_id": f"acc-a-{tenants['suffix']}",
            "target_cpm": 100,
        },
    )
    assert foreign_rule.status_code == 403

    brand = api_client.post(
        "/api/v1/pim/brands", headers=_as(tenants["key_a"]), json={"name": "Acme"}
    )
    assert brand.status_code == 201
    brand_id = brand.json()["brand_id"]
    assert api_client.get("/api/v1/pim/brands", headers=_as(tenants["key_b"])).json() == []
    stolen = api_client.patch(
        f"/api/v1/pim/brands/{brand_id}", headers=_as(tenants["key_b"]), json={"name": "Mine"}
    )
    assert stolen.status_code == 404

    users_b = api_client.get("/api/v1/users", headers=_as(tenants["key_b"])).json()
    assert tenants["user_a"] not in {u["user_id"] for u in users_b}
    assert all("api_key" not in u for u in users_b)


def test_rule_created_in_own_org_is_dry_run(
    api_client: TestClient, tenants: dict[str, Any]
) -> None:
    created = api_client.post(
        "/api/v1/repricer/rules",
        headers=_as(tenants["key_a"]),
        json={
            "marketplace": "wb",
            "account_id": f"acc-a-{tenants['suffix']}",
            "product_id": "123",
            "target_margin_percent": 10,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["dry_run"] is True
    listed_b = api_client.get("/api/v1/repricer/rules", headers=_as(tenants["key_b"])).json()
    assert created.json()["rule_id"] not in {r["rule_id"] for r in listed_b}


def test_revoked_key_stops_working(api_client: TestClient, tenants: dict[str, Any]) -> None:
    assert api_client.get("/api/v1/users/me", headers=_as(tenants["key_a"])).status_code == 200
    revoke = api_client.post(
        f"/api/v1/users/{tenants['user_a']}/revoke-key",
        headers=_admin(api_client, tenants["org_a"]),
    )
    assert revoke.status_code == 200
    assert api_client.get("/api/v1/users/me", headers=_as(tenants["key_a"])).status_code == 401


def test_insights_generation_is_per_org_and_idempotent(
    integration_runtime: Any, tenants: dict[str, Any]
) -> None:
    from app.tasks import insights

    suffix = tenants["suffix"]
    client = integration_runtime.ch_client()
    try:
        client.insert(
            "mrt_ads_daily",
            [
                [
                    date.today() - timedelta(days=2),
                    "wb",
                    f"acc-a-{suffix}",
                    "camp-a",
                    10,
                    1,
                    500.0,
                    0,
                    0.0,
                    0.0,
                    0.0,
                ],
                [
                    date.today() - timedelta(days=2),
                    "wb",
                    f"acc-b-{suffix}",
                    "camp-b",
                    10,
                    1,
                    700.0,
                    0,
                    0.0,
                    0.0,
                    0.0,
                ],
            ],
            column_names=[
                "day",
                "marketplace",
                "account_id",
                "campaign_id",
                "impressions",
                "clicks",
                "cost",
                "orders",
                "revenue",
                "acos",
                "romi",
            ],
        )
        insights.generate_actionable_tasks()
        insights.generate_actionable_tasks()
        rows = client.query(
            "SELECT organization_id, campaign_id FROM dim_actionable_task FINAL"
            " WHERE trigger_type = 'bad_ad' AND organization_id IN ({a:String}, {b:String})"
            " ORDER BY organization_id",
            parameters={"a": tenants["org_a"], "b": tenants["org_b"]},
        ).result_rows
    finally:
        client.close()

    assert sorted(rows) == sorted([(tenants["org_a"], "camp-a"), (tenants["org_b"], "camp-b")])


def test_audit_log_records_mutations(integration_runtime: Any, tenants: dict[str, Any]) -> None:
    client = integration_runtime.ch_client()
    try:
        rows = client.query(
            "SELECT actor, organization_id, status_code FROM sys_audit_log"
            " WHERE event = 'api_mutation' AND action = 'POST /api/v1/users'"
            " AND organization_id = {org:String}",
            parameters={"org": tenants["org_b"]},
        ).result_rows
    finally:
        client.close()
    assert rows and rows[0][0] == "platform-admin" and rows[0][2] == 201
