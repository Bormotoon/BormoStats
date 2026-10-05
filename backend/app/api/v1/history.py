"""History endpoints: a git-like log of every product card and statistics record."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AnalyticsReadAuth
from app.core.deps import ChClientDependency
from app.models.api import ListQueryParams, build_paginated_response, get_list_query_params
from app.services.history_service import HistoryService
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from common.history import PRODUCT_REPO

router = APIRouter(prefix="/history", tags=["history"], responses=API_ERROR_RESPONSES)

RepoParam = Annotated[
    str,
    Query(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="'product' or an archived statistics table such as 'raw_wb_sales'",
    ),
]
EntityKeyParam = Annotated[str, Query(max_length=512)]
SinceParam = Annotated[datetime | None, Query(description="Commits at or after (UTC)")]
UntilParam = Annotated[datetime | None, Query(description="Commits at or before (UTC)")]


@router.get("/repos")
def history_repos(
    *, auth: AnalyticsReadAuth, client: ChClientDependency
) -> dict[str, list[dict[str, Any]]]:
    """Entities and commit counts per repo: what the history store holds."""
    return {"items": HistoryService(client, auth.organization_id).repos()}


@router.get("/commits")
def history_commits(
    *,
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: ListQueryParams = Depends(get_list_query_params),
    repo: RepoParam = PRODUCT_REPO,
    entity_key: EntityKeyParam = "",
    since: SinceParam = None,
    until: UntilParam = None,
) -> dict[str, object]:
    """``git log``: commits newest first, optionally for one product or record."""
    items = HistoryService(client, auth.organization_id).commits(
        repo=repo,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        entity_key=entity_key,
        since=since,
        until=until,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    return build_paginated_response(items=items, limit=filters.limit, offset=filters.offset)


@router.get("/commits/{commit_id}")
def history_commit(
    commit_id: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    *,
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
) -> dict[str, Any]:
    """``git show``: one commit with the document it recorded and the fields it changed."""
    commit = HistoryService(client, auth.organization_id).commit(commit_id)
    if commit is None:
        raise HTTPException(status_code=404, detail="commit not found")
    return commit


@router.get("/snapshot")
def history_snapshot(
    *,
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    marketplace: Annotated[str, Query(pattern=r"^(wb|ozon)$")],
    entity_key: Annotated[str, Query(min_length=1, max_length=512)],
    account_id: Annotated[str, Query(max_length=64, pattern=r"^[A-Za-z0-9._:-]*$")] = "",
    repo: RepoParam = PRODUCT_REPO,
    at: Annotated[datetime | None, Query(description="Point in time (UTC); default now")] = None,
) -> dict[str, Any]:
    """``git checkout``: the product (or record) exactly as it was at ``at``."""
    snapshot = HistoryService(client, auth.organization_id).snapshot(
        repo=repo,
        marketplace=marketplace,
        account_id=account_id,
        entity_key=entity_key,
        at=at,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no history for this entity at that time")
    return snapshot


@router.get("/state")
def history_state(
    *,
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    repo: RepoParam,
    at: Annotated[datetime | None, Query(description="Point in time (UTC); default now")] = None,
    filters: ListQueryParams = Depends(get_list_query_params),
) -> dict[str, object]:
    """Every product (or record) of a repo exactly as it was at ``at``."""
    items = HistoryService(client, auth.organization_id).state(
        repo=repo,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        at=at,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    return build_paginated_response(
        items=items,
        limit=filters.limit,
        offset=filters.offset,
        repo=repo,
        at=at.isoformat() if at else None,
    )


@router.get("/changes")
def history_changes(
    *,
    auth: AnalyticsReadAuth,
    client: ChClientDependency,
    filters: ListQueryParams = Depends(get_list_query_params),
    repo: RepoParam = PRODUCT_REPO,
    entity_key: EntityKeyParam = "",
    path_prefix: Annotated[
        str,
        Query(max_length=256, description="Field path prefix, e.g. 'price' or 'card.title'"),
    ] = "",
    since: SinceParam = None,
    until: UntilParam = None,
) -> dict[str, object]:
    """Field-level history, newest first, e.g. every price change of one product."""
    items = HistoryService(client, auth.organization_id).changes(
        repo=repo,
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        entity_key=entity_key,
        path_prefix=path_prefix,
        since=since,
        until=until,
        limit=filters.query_limit,
        offset=filters.offset,
    )
    return build_paginated_response(items=items, limit=filters.limit, offset=filters.offset)
