"""Ingestion endpoints for the browser extension.

Each request is validated as a whole (422 lists every invalid item, nothing is
written), checked against the caller's accounts and written with one bulk INSERT.
Re-sending the same batch is harmless: the target tables are ReplacingMergeTree
keyed by the natural observation key, so duplicates collapse on merge.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AuthContext, CatalogWriteAuth
from app.core.deps import ChClientDependency
from app.models.extension import (
    MAX_EXTENSION_BATCH,
    CompetitorPrice,
    ExtensionIngestResult,
    SerpPosition,
)
from app.services.tenancy import ensure_account_access
from clickhouse_connect.driver import Client
from fastapi import APIRouter, Body, Header, status

router = APIRouter(prefix="/extension", tags=["extension"], responses=API_ERROR_RESPONSES)

BatchIdHeader = Annotated[uuid.UUID | None, Header(alias="X-Batch-Id")]


def _check_accounts(ch: Client, auth: AuthContext, accounts: set[tuple[str, str]]) -> None:
    for marketplace, account_id in sorted(accounts):
        ensure_account_access(ch, auth.organization_id, marketplace, account_id)


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def receive_positions(
    body: Annotated[list[SerpPosition], Body(min_length=1, max_length=MAX_EXTENSION_BATCH)],
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
    x_batch_id: BatchIdHeader = None,
) -> ExtensionIngestResult:
    batch_id = x_batch_id or uuid.uuid4()
    _check_accounts(ch, auth, {(item.marketplace, item.account_id) for item in body})
    ch.insert(
        "raw_serp_positions",
        [
            [
                batch_id,
                item.account_id,
                item.marketplace,
                item.keyword,
                item.product_id,
                item.position,
                item.search_ts,
            ]
            for item in body
        ],
        column_names=[
            "run_id",
            "account_id",
            "marketplace",
            "keyword",
            "product_id",
            "position",
            "search_ts",
        ],
    )
    return ExtensionIngestResult(inserted=len(body), batch_id=batch_id)


@router.post("/competitor-price", status_code=status.HTTP_201_CREATED)
def receive_competitor_price(
    body: Annotated[list[CompetitorPrice], Body(min_length=1, max_length=MAX_EXTENSION_BATCH)],
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
    x_batch_id: BatchIdHeader = None,
) -> ExtensionIngestResult:
    batch_id = x_batch_id or uuid.uuid4()
    _check_accounts(ch, auth, {(item.marketplace, item.account_id) for item in body})
    ch.insert(
        "raw_competitor_price_tracker",
        [
            [
                batch_id,
                item.account_id,
                item.marketplace,
                item.competitor_product_id,
                item.competitor_name,
                item.price_rub,
                item.price_with_discount_rub,
                1 if item.in_stock else 0,
                item.tracked_product_id,
                item.snapshot_ts,
            ]
            for item in body
        ],
        column_names=[
            "run_id",
            "account_id",
            "marketplace",
            "competitor_product_id",
            "competitor_name",
            "price_rub",
            "price_with_discount_rub",
            "in_stock",
            "tracked_product_id",
            "snapshot_ts",
        ],
    )
    return ExtensionIngestResult(inserted=len(body), batch_id=batch_id)
