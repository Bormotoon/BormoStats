"""Every API route must reject anonymous callers and scope tenants from the auth context."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from app.core.auth import AuthContext, AuthMethod, Scope, require_role
from app.core.config import get_settings
from app.core.deps import get_app_settings, get_ch_client
from app.main import app
from app.models.organization import OrgMemberRole
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.fakes import FakeClickHouse

PUBLIC_PATHS = {"/health", "/health/live", "/ready", "/health/ready", "/health/dependencies"}


def _api_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                routes.append((method, re.sub(r"\{[^}]+\}", "x1", route.path)))
    return routes


@pytest.fixture
def client() -> Iterator[TestClient]:
    ch = FakeClickHouse()
    app.dependency_overrides[get_ch_client] = lambda: ch
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_route_inventory_is_not_empty() -> None:
    assert len(_api_routes()) > 60


@pytest.mark.parametrize(("method", "path"), _api_routes())
def test_every_api_route_requires_credentials(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={})
    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.parametrize(("method", "path"), _api_routes())
def test_every_api_route_rejects_unknown_keys(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={}, headers={"X-API-Key": "not-a-real-key"})
    assert response.status_code == 401, (method, path, response.text)


def _context(role: OrgMemberRole, org: str = "org-a") -> AuthContext:
    from app.core.auth import ROLE_SCOPES

    return AuthContext(
        principal_id="u-1",
        organization_id=org,
        role=role,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[role],
    )


@pytest.fixture
def as_role(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    import app.core.auth as auth_module

    original = auth_module.resolve_auth_context

    def apply(role: OrgMemberRole, org: str = "org-a") -> None:
        monkeypatch.setattr(
            auth_module, "resolve_auth_context", lambda *a, **k: _context(role, org)
        )

    yield apply
    auth_module.resolve_auth_context = original


@pytest.mark.parametrize(
    ("role", "method", "path", "expected"),
    [
        (OrgMemberRole.viewer, "GET", "/api/v1/sales/daily", 200),
        (OrgMemberRole.viewer, "GET", "/api/v1/bidder/rules", 403),
        (OrgMemberRole.manager, "GET", "/api/v1/bidder/rules", 200),
        (OrgMemberRole.manager, "DELETE", "/api/v1/bidder/rules/r1", 403),
        (OrgMemberRole.analyst, "PATCH", "/api/v1/insights/tasks/t1", 403),
        (OrgMemberRole.viewer, "GET", "/api/v1/users", 403),
        (OrgMemberRole.admin, "GET", "/api/v1/users", 200),
        (OrgMemberRole.owner, "GET", "/api/v1/admin/watermarks", 401),
        (OrgMemberRole.owner, "GET", "/api/v1/organizations", 401),
    ],
)
def test_role_requirements(
    client: TestClient,
    as_role: Any,
    role: OrgMemberRole,
    method: str,
    path: str,
    expected: int,
) -> None:
    as_role(role)
    response = client.request(
        method, path, headers={"X-API-Key": "user-key"}, json={"status": "resolved"}
    )
    assert response.status_code == expected, response.text


def test_analytics_queries_are_scoped_to_caller_org(client: TestClient, as_role: Any) -> None:
    as_role(OrgMemberRole.viewer, org="org-a")
    ch = FakeClickHouse()
    app.dependency_overrides[get_ch_client] = lambda: ch
    for path in (
        "/api/v1/sales/daily",
        "/api/v1/stocks/current",
        "/api/v1/funnel/daily",
        "/api/v1/ads/daily",
        "/api/v1/kpis",
    ):
        response = client.get(
            path, headers={"X-API-Key": "user-key"}, params={"account_id": "someone-elses"}
        )
        assert response.status_code == 200, path
    assert len(ch.queries) == 5
    for sql, params in ch.queries:
        assert params["organization_id"] == "org-a"
        assert "FROM dim_account FINAL WHERE organization_id = %(organization_id)s" in sql


def test_user_cannot_create_higher_role_than_own(client: TestClient, as_role: Any) -> None:
    as_role(OrgMemberRole.admin)
    response = client.post(
        "/api/v1/users",
        headers={"X-API-Key": "user-key"},
        json={"name": "Eve", "email": "eve@example.com", "org_role": OrgMemberRole.owner.value},
    )
    assert response.status_code == 403


def test_only_platform_admin_moves_users_between_orgs(client: TestClient, as_role: Any) -> None:
    as_role(OrgMemberRole.owner)
    response = client.patch(
        "/api/v1/users/u-2",
        headers={"X-API-Key": "user-key"},
        json={"organization_id": "org-b"},
    )
    assert response.status_code == 403


def test_disabling_dry_run_requires_marketplace_scope(client: TestClient, as_role: Any) -> None:
    scopes_without_execute = frozenset({Scope.read_analytics, Scope.write_settings})
    import app.core.auth as auth_module

    ctx = AuthContext(
        principal_id="u",
        organization_id="org-a",
        role=OrgMemberRole.admin,
        auth_method=AuthMethod.user_key,
        scopes=scopes_without_execute,
    )
    auth_module.resolve_auth_context = lambda *a, **k: ctx  # type: ignore[assignment]
    response = client.patch(
        "/api/v1/repricer/rules/r1", headers={"X-API-Key": "k"}, json={"dry_run": False}
    )
    assert response.status_code == 403
    assert "execute:marketplace" in response.json()["detail"]


def test_openapi_schema_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").status_code == 401
    response = client.get("/api/v1/openapi.json", headers={"X-API-Key": "test-admin-key"})
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Marketplace Analytics API"


def test_metrics_requires_bearer_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "metrics_bearer_token", "scrape-token")
    assert client.get("/metrics").status_code == 401
    ok = client.get("/metrics", headers={"Authorization": "Bearer scrape-token"})
    assert ok.status_code == 200


def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
    generated = client.get("/health").headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)


def test_settings_dependency_is_real_settings() -> None:
    assert get_app_settings() is get_settings()
    assert require_role(OrgMemberRole.viewer) is not None
