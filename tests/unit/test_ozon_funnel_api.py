from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from app.api.v1.funnel import (
    OzonFunnelImport,
    OzonFunnelRow,
    ozon_funnel,
    ozon_funnel_related,
)
from app.core.auth import ROLE_SCOPES, AuthContext, AuthMethod
from app.models.api import DateRangeQueryParams
from app.models.organization import OrgMemberRole


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
