"""Shared API contract helpers and models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

DEFAULT_PAGE_LIMIT = 1000
MAX_PAGE_LIMIT = 2000
MAX_PAGE_OFFSET = 50_000
DEFAULT_DATE_WINDOW_DAYS = 30
MAX_DATE_WINDOW_DAYS = 92

MarketplaceFilter = Literal["wb", "ozon"] | None


class ApiError(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ApiErrorResponse(BaseModel):
    detail: str
    error: ApiError


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    returned: int
    next_offset: int | None
    has_more: bool


@dataclass(frozen=True)
class ListQueryParams:
    marketplace: str
    account_id: str
    limit: int
    offset: int

    @property
    def query_limit(self) -> int:
        return self.limit + 1


@dataclass(frozen=True)
class DateRangeQueryParams(ListQueryParams):
    date_from: date
    date_to: date


def build_paginated_response(
    *,
    items: list[dict[str, Any]],
    limit: int,
    offset: int,
    **payload: Any,
) -> dict[str, Any]:
    has_more = len(items) > limit
    visible_items = items[:limit]
    return {
        **payload,
        "items": visible_items,
        "pagination": PaginationMeta(
            limit=limit,
            offset=offset,
            returned=len(visible_items),
            next_offset=(offset + limit) if has_more else None,
            has_more=has_more,
        ).model_dump(mode="json"),
    }


def _normalized_filter(value: str | None) -> str:
    return value or ""


def _validation_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def get_list_query_params(
    marketplace: Annotated[MarketplaceFilter, Query()] = None,
    account_id: Annotated[
        str | None,
        Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_LIMIT),
    ] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)] = 0,
) -> ListQueryParams:
    return ListQueryParams(
        marketplace=_normalized_filter(marketplace),
        account_id=_normalized_filter(account_id),
        limit=limit,
        offset=offset,
    )


def get_date_range_query_params(
    filters: Annotated[ListQueryParams, Depends(get_list_query_params)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> DateRangeQueryParams:
    resolved_to = date_to or datetime.now(UTC).date()
    resolved_from = date_from or (resolved_to - timedelta(days=DEFAULT_DATE_WINDOW_DAYS))

    if resolved_from > resolved_to:
        raise _validation_error("date_from must be on or before date_to")

    if (resolved_to - resolved_from).days > MAX_DATE_WINDOW_DAYS:
        raise _validation_error(f"date window must not exceed {MAX_DATE_WINDOW_DAYS} days")

    return DateRangeQueryParams(
        marketplace=filters.marketplace,
        account_id=filters.account_id,
        limit=filters.limit,
        offset=filters.offset,
        date_from=resolved_from,
        date_to=resolved_to,
    )
