"""History API: tenant scoping, filters, and how stored JSON is decoded."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from app.core.auth import ROLE_SCOPES, AuthContext, AuthMethod
from app.core.deps import get_ch_client
from app.main import app
from app.models.organization import OrgMemberRole
from fastapi.testclient import TestClient

from tests.fakes import FakeClickHouse

COMMIT = "a" * 64
HEADERS = {"X-API-Key": "user-key"}


@pytest.fixture
def ch(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClickHouse]:
    import app.core.auth as auth_module

    context = AuthContext(
        principal_id="u-1",
        organization_id="org-a",
        role=OrgMemberRole.viewer,
        auth_method=AuthMethod.user_key,
        scopes=ROLE_SCOPES[OrgMemberRole.viewer],
    )
    monkeypatch.setattr(auth_module, "resolve_auth_context", lambda *a, **k: context)
    fake = FakeClickHouse()
    app.dependency_overrides[get_ch_client] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(ch: FakeClickHouse) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _commit_row(**overrides: Any) -> dict[str, Any]:
    return {
        "commit_id": COMMIT,
        "marketplace": "wb",
        "account_id": "acc",
        "repo": "product",
        "entity_key": "1",
        "parent_id": "",
        "object_hash": "h1",
        "is_deleted": 0,
        "committed_at": datetime(2026, 9, 1, 10, 0, 0),
        "run_id": "r",
        "source": "wb_catalog",
        "message": "initial",
        "changed_paths": [],
        **overrides,
    }


def test_every_history_query_is_scoped_to_the_callers_organization(
    client: TestClient, ch: FakeClickHouse
) -> None:
    ch.on("FROM hist_commits", [_commit_row()])
    ch.on("FROM hist_changes", [])
    ch.on("FROM hist_refs", [])
    for path, params in (
        ("/api/v1/history/repos", {}),
        ("/api/v1/history/commits", {"account_id": "someone-elses"}),
        ("/api/v1/history/changes", {"account_id": "someone-elses"}),
        (f"/api/v1/history/commits/{COMMIT}", {}),
        ("/api/v1/history/snapshot", {"marketplace": "wb", "entity_key": "1"}),
    ):
        assert client.get(path, headers=HEADERS, params=params).status_code in (200, 404), path

    scoped = [(sql, p) for sql, p in ch.queries if "hist_commits" in sql or "hist_refs" in sql]
    assert scoped
    for sql, params in ch.queries:
        if "FROM hist_objects" in sql:
            continue  # objects are only reached through a commit that passed the scope
        assert params["organization_id"] == "org-a", sql
        assert "FROM dim_account FINAL WHERE organization_id = {organization_id:String}" in sql


def test_commit_log_paginates_and_filters_by_entity(client: TestClient, ch: FakeClickHouse) -> None:
    ch.on("FROM hist_commits", [_commit_row(entity_key="1"), _commit_row(entity_key="1")])

    body = client.get(
        "/api/v1/history/commits",
        headers=HEADERS,
        params={"marketplace": "wb", "entity_key": "1", "limit": 1},
    ).json()

    assert body["pagination"]["has_more"] is True and len(body["items"]) == 1
    _, params = ch.queries[-1]
    assert params["repo"] == "product" and params["entity_key"] == "1"
    assert params["marketplace"] == "wb" and params["limit"] == 2


def test_commit_detail_decodes_document_and_changes(client: TestClient, ch: FakeClickHouse) -> None:
    ch.on("FROM hist_commits", [_commit_row(changed_paths=["price.price"])])
    ch.on(
        "FROM hist_changes",
        [{"path": "price.price", "op": "change", "old_value": "1000", "new_value": "900"}],
    )
    ch.on("FROM hist_objects", [{"body": '{"price":{"price":900}}'}])

    body = client.get(f"/api/v1/history/commits/{COMMIT}", headers=HEADERS).json()

    assert body["document"] == {"price": {"price": 900}}
    assert body["changes"] == [
        {"path": "price.price", "op": "change", "old_value": 1000, "new_value": 900}
    ]


def test_unknown_commit_is_404_and_malformed_id_is_422(client: TestClient) -> None:
    assert client.get(f"/api/v1/history/commits/{COMMIT}", headers=HEADERS).status_code == 404
    assert client.get("/api/v1/history/commits/nope", headers=HEADERS).status_code == 422


def test_snapshot_returns_document_as_of_the_requested_time(
    client: TestClient, ch: FakeClickHouse
) -> None:
    ch.on("FROM hist_commits", [_commit_row(is_deleted=0)])
    ch.on("FROM hist_objects", [{"body": '{"card":{"title":"Mug"}}'}])

    body = client.get(
        "/api/v1/history/snapshot",
        headers=HEADERS,
        params={"marketplace": "wb", "entity_key": "1", "at": "2026-09-02T00:00:00+03:00"},
    ).json()

    assert body["document"] == {"card": {"title": "Mug"}} and body["is_deleted"] is False
    commit_query = next(p for sql, p in ch.queries if "hist_commits" in sql)
    assert commit_query["at"] == datetime(2026, 9, 1, 21, 0, 0, tzinfo=UTC)


def test_snapshot_of_a_deleted_product_has_no_document(
    client: TestClient, ch: FakeClickHouse
) -> None:
    ch.on("FROM hist_commits", [_commit_row(is_deleted=1)])

    body = client.get(
        "/api/v1/history/snapshot",
        headers=HEADERS,
        params={"marketplace": "wb", "entity_key": "1"},
    ).json()

    assert body["is_deleted"] is True and body["document"] is None


def test_snapshot_without_history_is_404(client: TestClient) -> None:
    response = client.get(
        "/api/v1/history/snapshot",
        headers=HEADERS,
        params={"marketplace": "wb", "entity_key": "missing"},
    )
    assert response.status_code == 404


def test_changes_filter_by_path_prefix(client: TestClient, ch: FakeClickHouse) -> None:
    ch.on(
        "FROM hist_changes",
        [
            {
                "marketplace": "wb",
                "account_id": "acc",
                "repo": "product",
                "entity_key": "1",
                "path": "price.price",
                "commit_id": COMMIT,
                "committed_at": datetime(2026, 9, 1),
                "op": "change",
                "old_value": "1000",
                "new_value": "900",
            }
        ],
    )

    body = client.get(
        "/api/v1/history/changes",
        headers=HEADERS,
        params={"entity_key": "1", "path_prefix": "price", "since": "2026-09-01T00:00:00"},
    ).json()

    assert body["items"][0]["old_value"] == 1000 and body["items"][0]["new_value"] == 900
    _, params = ch.queries[-1]
    assert params["path_prefix"] == "price"
    assert params["since"] == datetime(2026, 9, 1, tzinfo=UTC)  # naive input is read as UTC


def test_repo_names_are_validated(client: TestClient) -> None:
    response = client.get("/api/v1/history/commits", headers=HEADERS, params={"repo": "a; DROP"})
    assert response.status_code == 422
