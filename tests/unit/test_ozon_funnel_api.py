from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.api.v1.funnel import (
    OzonFunnelImport,
    OzonFunnelRow,
    ozon_funnel,
    ozon_funnel_finance,
    ozon_funnel_related,
)
from app.core.auth import ROLE_SCOPES, AuthContext, AuthMethod
from app.models.api import DateRangeQueryParams
from app.models.organization import OrgMemberRole
from pydantic import ValidationError


def test_ozon_funnel_pagination_order_deterministic() -> None:
    """Fixes Copilot #6: ORDER BY day DESC, account_id ASC, sku ASC, scheme ASC."""
    client = MagicMock()
    client.query.return_value.named_results.return_value = []
    auth = AuthContext(
        principal_id="user1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    filters = DateRangeQueryParams(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        marketplace="ozon",
        account_id="",
        limit=10,
        offset=0,
    )
    ozon_funnel(auth=auth, client=client, filters=filters)
    sql_called = client.query.call_args[0][0]
    assert "ORDER BY day DESC, account_id ASC, sku ASC, scheme ASC" in sql_called
    assert "raw_ozon_funnel_import" in sql_called


def test_ozon_funnel_related_cost_leak_protection() -> None:
    """Fixes Copilot #1: cost_price_rub and dim_offer_cost must not be queried for viewer role."""
    client = MagicMock()
    client.query.return_value.named_results.return_value = []
    filters = DateRangeQueryParams(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        marketplace="ozon",
        account_id="",
        limit=10,
        offset=0,
    )

    # Viewer role: must NOT include 'cost' kind or touch dim_offer_cost
    viewer_auth = AuthContext(
        principal_id="viewer1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    ozon_funnel_related(auth=viewer_auth, client=client, filters=filters)
    viewer_sql = client.query.call_args[0][0]
    assert "dim_offer_cost" not in viewer_sql
    assert "'cost' AS kind" not in viewer_sql

    # Manager role: allowed to query dim_offer_cost
    manager_auth = AuthContext(
        principal_id="mgr1",
        organization_id="org1",
        role=OrgMemberRole.manager,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.manager],
    )
    ozon_funnel_related(auth=manager_auth, client=client, filters=filters)
    manager_sql = client.query.call_args[0][0]
    assert "dim_offer_cost" in manager_sql
    assert "'cost' AS kind" in manager_sql


def test_ozon_funnel_import_uniqueness_validation() -> None:
    row1 = OzonFunnelRow(
        day=date(2026, 10, 1),
        sku="12345",
        scheme="fbo",
        position=1.0,
        impressions=100,
        search_impressions=50,
        clicks=10,
        carts=2,
    )
    row2 = OzonFunnelRow(
        day=date(2026, 10, 1),
        sku="12345",
        scheme="fbo",
        position=2.0,
        impressions=200,
        search_impressions=100,
        clicks=20,
        carts=4,
    )
    with pytest.raises(ValueError, match="Повторяются строки"):
        OzonFunnelImport(account_id="acc1", rows=[row1, row2])


def _sample_finance_payload() -> str:
    return json.dumps(
        {
            "date": "2026-10-05T00:00:00",
            "posting": {
                "products": [
                    {
                        "sku": 100,
                        "quantity": 1,
                        "commission": {
                            "sale_amount": {"amount": "1000"},
                            "sale_price": {"amount": "800"},
                            "commission": {"amount": "-150"},
                        },
                    }
                ]
            },
        }
    )


def test_ozon_funnel_finance_redacts_sensitive_fields_for_viewer() -> None:
    client = MagicMock()

    def mock_query(sql: str, parameters: dict[str, Any] | None = None) -> Any:
        res = MagicMock()
        if "raw_ozon_finance_ops" in sql:
            res.result_rows = [("acc1", _sample_finance_payload())]
        elif "dim_additional_expense" in sql:
            res.result_rows = [(1,)]
        else:
            res.result_rows = []
        return res

    client.query.side_effect = mock_query
    auth = AuthContext(
        principal_id="viewer1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    filters = DateRangeQueryParams(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        marketplace="ozon",
        account_id="acc1",
        limit=10,
        offset=0,
    )
    out = ozon_funnel_finance(auth=auth, client=client, filters=filters)
    assert out["external"] is None
    assert out["tax_rate"] is None
    assert len(out["daily"]) > 0
    for r in out["daily"]:
        assert r["revenue"] == 0.0
        assert r["buyer"] == 0.0
        assert r["mp_cost"] == 0.0
        assert r["sold"] >= 1


def test_ozon_funnel_finance_shows_sensitive_fields_for_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PNL_TAX_RATE_PCT", "8")
    monkeypatch.setenv("PNL_TAX_ACCOUNT_ID", "acc1")
    client = MagicMock()

    def mock_query(sql: str, parameters: dict[str, Any] | None = None) -> Any:
        res = MagicMock()
        if "raw_ozon_finance_ops" in sql:
            res.result_rows = [("acc1", _sample_finance_payload())]
        elif "dim_additional_expense" in sql:
            res.result_rows = [(1,)]
        else:
            res.result_rows = []
        return res

    client.query.side_effect = mock_query
    auth = AuthContext(
        principal_id="mgr1",
        organization_id="org1",
        role=OrgMemberRole.manager,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.manager],
    )
    filters = DateRangeQueryParams(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        marketplace="ozon",
        account_id="acc1",
        limit=10,
        offset=0,
    )
    out = ozon_funnel_finance(auth=auth, client=client, filters=filters)
    assert out["external"] is not None and out["external"] > 0
    assert out["tax_rate"] is not None and out["tax_rate"] > 0
    assert len(out["daily"]) > 0
    for r in out["daily"]:
        assert r["revenue"] > 0.0
        assert r["buyer"] > 0.0
        assert r["mp_cost"] != 0.0


def test_ozon_funnel_import_rejects_too_many_partitions() -> None:
    rows = [
        OzonFunnelRow(
            day=date(2020 + i // 12, (i % 12) + 1, 1),
            sku=f"100{i}",
            scheme="fbo",
            position=1.0,
            impressions=10,
            search_impressions=5,
            clicks=2,
            carts=1,
        )
        for i in range(25)
    ]
    with pytest.raises(ValidationError, match="monthly partitions"):
        OzonFunnelImport(account_id="acc1", rows=rows)


def test_ozon_funnel_import_rejects_out_of_range_date() -> None:
    with pytest.raises(ValidationError):
        OzonFunnelRow(
            day=date(1999, 1, 1),
            sku="123",
            position=1.0,
            impressions=10,
            search_impressions=5,
            clicks=2,
            carts=1,
        )
    with pytest.raises(ValidationError):
        OzonFunnelRow(
            day=date(2101, 1, 1),
            sku="123",
            position=1.0,
            impressions=10,
            search_impressions=5,
            clicks=2,
            carts=1,
        )


def test_funnel_import_alphanumeric_sku_for_ym_and_wb() -> None:
    # YM style SKU with hyphens, dots, underscores, colons
    row_ym = OzonFunnelRow(
        day=date(2026, 10, 1),
        sku="YM-SKU_123.A:45",
        scheme="fbo",
        position=1.0,
        impressions=10,
        search_impressions=5,
        clicks=2,
        carts=1,
    )
    payload_ym = OzonFunnelImport(account_id="acc_ym", marketplace="ym", rows=[row_ym])
    assert payload_ym.marketplace == "ym"
    assert payload_ym.rows[0].sku == "YM-SKU_123.A:45"

    # WB style integer SKU string
    row_wb = OzonFunnelRow(
        day=date(2026, 10, 1),
        sku="987654321",
        scheme="fbo",
        position=1.0,
        impressions=10,
        search_impressions=5,
        clicks=2,
        carts=1,
    )
    payload_wb = OzonFunnelImport(account_id="acc_wb", marketplace="wb", rows=[row_wb])
    assert payload_wb.marketplace == "wb"

    # Disallowed characters (e.g. whitespace, slashes, quotes) should fail regex
    with pytest.raises(ValidationError):
        OzonFunnelRow(
            day=date(2026, 10, 1),
            sku="INVALID SKU SPACES",
            position=1.0,
            impressions=10,
            search_impressions=5,
            clicks=2,
            carts=1,
        )


def test_funnel_related_wb_and_ym() -> None:
    client = MagicMock()
    client.query.return_value.named_results.return_value = []
    viewer_auth = AuthContext(
        principal_id="viewer1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    manager_auth = AuthContext(
        principal_id="mgr1",
        organization_id="org1",
        role=OrgMemberRole.manager,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.manager],
    )

    for mp in ["wb", "ym"]:
        filters = DateRangeQueryParams(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 7),
            marketplace=mp,
            account_id="acc1",
            limit=10,
            offset=0,
        )

        # Viewer check
        ozon_funnel_related(auth=viewer_auth, client=client, filters=filters)
        viewer_sql = client.query.call_args[0][0]
        assert "stg_orders" in viewer_sql
        assert "stg_sales" in viewer_sql
        assert "dim_offer_cost" not in viewer_sql

        # Manager check
        ozon_funnel_related(auth=manager_auth, client=client, filters=filters)
        manager_sql = client.query.call_args[0][0]
        assert "stg_orders" in manager_sql
        assert "stg_sales" in manager_sql
        assert "dim_offer_cost" in manager_sql


def test_funnel_finance_wb_and_ym() -> None:
    client = MagicMock()

    def mock_query(sql: str, parameters: dict[str, Any] | None = None) -> Any:
        res = MagicMock()
        if "mrt_finance_daily" in sql:
            res.named_results.return_value = [
                {
                    "day": "2026-10-05",
                    "account_id": "acc_wb",
                    "revenue": 5000.0,
                    "buyer": 5000.0,
                    "mp_cost": -1200.0,
                    "sales_raw": 5000.0,
                    "returns_raw": 0.0,
                }
            ]
        elif "mrt_ad_performance_daily" in sql:
            res.named_results.return_value = [
                {
                    "account_id": "acc_wb",
                    "day": "2026-10-05",
                    "sku": "12345",
                    "campaign_id": "c1",
                    "amount": 350.0,
                    "kind": "search",
                    "title": "Campaign 1",
                }
            ]
        elif "mrt_stock_daily" in sql:
            res.named_results.return_value = [
                {
                    "account_id": "acc_wb",
                    "day": "2026-10-05",
                    "sku": "12345",
                    "available": 50,
                    "reserved": 0,
                    "present": 50,
                }
            ]
            res.result_rows = [("2026-10-01",)]
        elif "dim_additional_expense" in sql:
            res.result_rows = [(2,)]
        else:
            res.named_results.return_value = []
            res.result_rows = []
        return res

    client.query.side_effect = mock_query

    viewer_auth = AuthContext(
        principal_id="viewer1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    manager_auth = AuthContext(
        principal_id="mgr1",
        organization_id="org1",
        role=OrgMemberRole.manager,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.manager],
    )

    filters = DateRangeQueryParams(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        marketplace="wb",
        account_id="acc_wb",
        limit=10,
        offset=0,
    )

    # Viewer: sensitive fields redacted
    viewer_out = ozon_funnel_finance(auth=viewer_auth, client=client, filters=filters)
    assert viewer_out["external"] is None
    assert viewer_out["tax_rate"] is None
    assert len(viewer_out["daily"]) == 1
    assert viewer_out["daily"][0]["revenue"] == 0.0
    assert viewer_out["daily"][0]["mp_cost"] == 0.0
    assert viewer_out["daily"][0]["sold"] == 1
    assert len(viewer_out["advertising"]) == 1
    assert viewer_out["advertising"][0]["amount"] == 0.0
    assert len(viewer_out["stocks"]) == 1
    assert viewer_out["stocks"][0]["available"] == 50

    # Manager: sensitive fields visible
    manager_out = ozon_funnel_finance(auth=manager_auth, client=client, filters=filters)
    assert manager_out["external"] == 2
    assert len(manager_out["daily"]) == 1
    assert manager_out["daily"][0]["revenue"] == 5000.0
    assert manager_out["daily"][0]["mp_cost"] == -1200.0
    assert manager_out["daily"][0]["sold"] == 1
    assert len(manager_out["advertising"]) == 1
    assert manager_out["advertising"][0]["amount"] == 350.0


def test_funnel_import_alphanumeric_sku_for_ym_and_wb() -> None:
    # YM style SKU with hyphens, dots, underscores, colons
    row_ym = OzonFunnelRow(
        day=date(2026, 10, 1),
        sku="YM-SKU_123.A:45",
        scheme="fbo",
        position=1.0,
        impressions=10,
        search_impressions=5,
        clicks=2,
        carts=1,
    )
    payload_ym = OzonFunnelImport(account_id="acc_ym", marketplace="ym", rows=[row_ym])
    assert payload_ym.marketplace == "ym"
    assert payload_ym.rows[0].sku == "YM-SKU_123.A:45"

    # WB style integer SKU string
    row_wb = OzonFunnelRow(
        day=date(2026, 10, 1),
        sku="987654321",
        scheme="fbo",
        position=1.0,
        impressions=10,
        search_impressions=5,
        clicks=2,
        carts=1,
    )
    payload_wb = OzonFunnelImport(account_id="acc_wb", marketplace="wb", rows=[row_wb])
    assert payload_wb.marketplace == "wb"

    # Disallowed characters (e.g. whitespace, slashes, quotes) should fail regex
    with pytest.raises(ValidationError):
        OzonFunnelRow(
            day=date(2026, 10, 1),
            sku="INVALID SKU SPACES",
            position=1.0,
            impressions=10,
            search_impressions=5,
            clicks=2,
            carts=1,
        )


def test_funnel_related_wb_and_ym() -> None:
    client = MagicMock()
    client.query.return_value.named_results.return_value = []
    viewer_auth = AuthContext(
        principal_id="viewer1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    manager_auth = AuthContext(
        principal_id="mgr1",
        organization_id="org1",
        role=OrgMemberRole.manager,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.manager],
    )

    for mp in ["wb", "ym"]:
        filters = DateRangeQueryParams(
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 7),
            marketplace=mp,
            account_id="acc1",
            limit=10,
            offset=0,
        )

        # Viewer check
        ozon_funnel_related(auth=viewer_auth, client=client, filters=filters)
        viewer_sql = client.query.call_args[0][0]
        assert "stg_orders" in viewer_sql
        assert "stg_sales" in viewer_sql
        assert "dim_offer_cost" not in viewer_sql

        # Manager check
        ozon_funnel_related(auth=manager_auth, client=client, filters=filters)
        manager_sql = client.query.call_args[0][0]
        assert "stg_orders" in manager_sql
        assert "stg_sales" in manager_sql
        assert "dim_offer_cost" in manager_sql


def test_funnel_finance_wb_and_ym() -> None:
    client = MagicMock()

    def mock_query(sql: str, parameters: dict[str, Any] | None = None) -> Any:
        res = MagicMock()
        if "mrt_finance_daily" in sql:
            res.named_results.return_value = [
                {
                    "day": "2026-10-05",
                    "account_id": "acc_wb",
                    "revenue": 5000.0,
                    "buyer": 5000.0,
                    "mp_cost": -1200.0,
                    "sales_raw": 5000.0,
                    "returns_raw": 0.0,
                }
            ]
        elif "mrt_ad_performance_daily" in sql:
            res.named_results.return_value = [
                {
                    "account_id": "acc_wb",
                    "day": "2026-10-05",
                    "sku": "12345",
                    "campaign_id": "c1",
                    "amount": 350.0,
                    "kind": "search",
                    "title": "Campaign 1",
                }
            ]
        elif "mrt_stock_daily" in sql:
            res.named_results.return_value = [
                {
                    "account_id": "acc_wb",
                    "day": "2026-10-05",
                    "sku": "12345",
                    "available": 50,
                    "reserved": 0,
                    "present": 50,
                }
            ]
            res.result_rows = [("2026-10-01",)]
        elif "dim_additional_expense" in sql:
            res.result_rows = [(2,)]
        else:
            res.named_results.return_value = []
            res.result_rows = []
        return res

    client.query.side_effect = mock_query

    viewer_auth = AuthContext(
        principal_id="viewer1",
        organization_id="org1",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    manager_auth = AuthContext(
        principal_id="mgr1",
        organization_id="org1",
        role=OrgMemberRole.manager,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.manager],
    )

    filters = DateRangeQueryParams(
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        marketplace="wb",
        account_id="acc_wb",
        limit=10,
        offset=0,
    )

    # Viewer: sensitive fields redacted
    viewer_out = ozon_funnel_finance(auth=viewer_auth, client=client, filters=filters)
    assert viewer_out["external"] is None
    assert viewer_out["tax_rate"] is None
    assert len(viewer_out["daily"]) == 1
    assert viewer_out["daily"][0]["revenue"] == 0.0
    assert viewer_out["daily"][0]["mp_cost"] == 0.0
    assert viewer_out["daily"][0]["sold"] == 1
    assert len(viewer_out["advertising"]) == 1
    assert viewer_out["advertising"][0]["amount"] == 0.0
    assert len(viewer_out["stocks"]) == 1
    assert viewer_out["stocks"][0]["available"] == 50

    # Manager: sensitive fields visible
    manager_out = ozon_funnel_finance(auth=manager_auth, client=client, filters=filters)
    assert manager_out["external"] == 2
    assert len(manager_out["daily"]) == 1
    assert manager_out["daily"][0]["revenue"] == 5000.0
    assert manager_out["daily"][0]["mp_cost"] == -1200.0
    assert manager_out["daily"][0]["sold"] == 1
    assert len(manager_out["advertising"]) == 1
    assert manager_out["advertising"][0]["amount"] == 350.0

