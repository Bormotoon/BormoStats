"""History store tasks: product catalogue snapshots and the one-off raw archive import."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import httpx
from app.utils.celery_helpers import shared_task
from app.utils.history_archive import (
    STAT_SPECS,
    backfill_done,
    backfill_table,
    retire_legacy_entities,
)
from app.utils.history_store import (
    HistoryStore,
    Observation,
    history_enabled,
    ignore_patterns,
)
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.metrics import observe_empty_payload
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

from collectors.ozon.client import OzonApiClient
from collectors.ozon.errors import is_capability_error
from collectors.ozon.parsers import build_ozon_products
from collectors.wb.client import WbCatalogClient
from collectors.wb.parsers import build_wb_products
from common.history import PRODUCT_REPO

LOGGER = logging.getLogger(__name__)

WB_ACCOUNT_ID = os.getenv("WB_ACCOUNT_ID", "default")
OZON_ACCOUNT_ID = os.getenv("OZON_ACCOUNT_ID", "default")
PRODUCT_IGNORE_ENV = "HISTORY_PRODUCT_IGNORE_PATHS"
# a token without the catalogue scope answers 401/403; that must not fail the whole snapshot
_WB_SCOPE_STATUSES = {401, 403}


def _optional_section_wb(name: str, fetch: Callable[[], list[dict[str, Any]]]) -> Any:
    try:
        return fetch()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in _WB_SCOPE_STATUSES:
            LOGGER.warning("wb %s not readable with the configured token: %s", name, exc)
            return None
        raise


def _optional_section_ozon(name: str, fetch: Callable[[], list[dict[str, Any]]]) -> Any:
    try:
        return fetch()
    except Exception as exc:
        if is_capability_error(exc):
            LOGGER.warning("ozon %s not readable for this seller: %s", name, exc)
            return None
        raise


def _commit_catalogue(
    *,
    task_name: str,
    source: str,
    marketplace: str,
    account_id: str,
    build: Callable[[], tuple[dict[str, dict[str, Any]], tuple[str, ...]]],
) -> dict[str, Any]:
    run_id, started_at = new_run_context()
    if not history_enabled():
        return {"status": "skipped", "reason": "history disabled"}
    redis_client = get_redis_client()
    try:
        with lock_scope(
            redis_client=redis_client,
            source=source,
            account_id=account_id,
            ttl_seconds=1800,
            auto_renew=True,
        ) as lock:
            ch_client = get_ch_client()
            try:
                documents, carry = build()
                lock.ensure_held()
                if not documents:
                    observe_empty_payload(source)
                result = HistoryStore(ch_client, run_id=run_id, source=source).record(
                    marketplace=marketplace,
                    account_id=account_id,
                    repo=PRODUCT_REPO,
                    observations=[Observation(key, doc) for key, doc in documents.items()],
                    ignore=ignore_patterns(PRODUCT_IGNORE_ENV),
                    # an empty listing is more likely a broken response than an empty shop
                    tombstone_missing=bool(documents),
                    carry=carry,
                )
                meta = result.as_meta()
                log_task_run(
                    ch_client,
                    task_name,
                    run_id,
                    started_at,
                    "success",
                    result.commits,
                    f"{source}: {result.seen} products, {result.commits} commits",
                    meta=meta,
                )
                return {"status": "success", **meta}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}


@shared_task(name="tasks.history.wb_catalog_snapshot")
def wb_catalog_snapshot(account_id: str = WB_ACCOUNT_ID) -> dict[str, Any]:
    content_token = os.getenv("WB_TOKEN_CONTENT", "").strip()
    if not content_token:
        return {"status": "skipped", "reason": "missing WB_TOKEN_CONTENT"}
    prices_token = os.getenv("WB_TOKEN_PRICES", "").strip()

    def build() -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
        with WbCatalogClient(content_token, prices_token) as wb:
            cards = wb.cards()
            prices = _optional_section_wb("prices", wb.prices) if prices_token else None
        return build_wb_products(cards, prices), (() if prices is not None else ("price",))

    return _commit_catalogue(
        task_name="tasks.history.wb_catalog_snapshot",
        source="wb_catalog",
        marketplace="wb",
        account_id=account_id,
        build=build,
    )


@shared_task(name="tasks.history.ozon_catalog_snapshot")
def ozon_catalog_snapshot(account_id: str = OZON_ACCOUNT_ID) -> dict[str, Any]:
    client_id = os.getenv("OZON_CLIENT_ID", "")
    api_key = os.getenv("OZON_API_KEY", "")
    if not client_id or not api_key:
        return {"status": "skipped", "reason": "missing Ozon credentials"}

    def build() -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
        with OzonApiClient(client_id=client_id, api_key=api_key) as ozon:
            ids = ozon.product_ids()
            if not ids:
                return {}, ()
            info = ozon.product_info(ids)
            attributes = _optional_section_ozon("attributes", lambda: ozon.product_attributes(ids))
            prices = _optional_section_ozon("prices", lambda: ozon.product_prices(ids))
        carry = tuple(
            section
            for section, value in (("attributes", attributes), ("price", prices))
            if value is None
        )
        return build_ozon_products(ids, info, attributes, prices), carry

    return _commit_catalogue(
        task_name="tasks.history.ozon_catalog_snapshot",
        source="ozon_catalog",
        marketplace="ozon",
        account_id=account_id,
        build=build,
    )


@shared_task(name="tasks.history.backfill_raw_archive")
def backfill_raw_archive() -> dict[str, Any]:
    """Import the current contents of each raw table into the archive, once per table.

    ``prune_old_raw`` refuses to delete from a table until it has been imported here.
    """
    task_name = "tasks.history.backfill_raw_archive"
    run_id, started_at = new_run_context()
    if not history_enabled():
        return {"status": "skipped", "reason": "history disabled"}
    redis_client = get_redis_client()
    try:
        with lock_scope(
            redis_client=redis_client,
            source="history_backfill",
            account_id="all",
            ttl_seconds=3600,
            auto_renew=True,
        ) as lock:
            ch_client = get_ch_client()
            imported: dict[str, dict[str, int]] = {}
            try:
                for table in STAT_SPECS:
                    lock.ensure_held()
                    if backfill_done(ch_client, table):
                        continue
                    imported[table] = backfill_table(ch_client, table, run_id=run_id)
                retired = retire_legacy_entities(ch_client, run_id=run_id)
                commits = sum(item["commits"] for item in imported.values())
                log_task_run(
                    ch_client,
                    task_name,
                    run_id,
                    started_at,
                    "success",
                    commits,
                    f"raw archive import: {len(imported)} table(s)",
                    meta={"tables": imported, "retired": retired},
                )
                return {"status": "success", "tables": imported, "retired": retired}
            except Exception as exc:
                log_task_run(ch_client, task_name, run_id, started_at, "failed", 0, str(exc))
                raise
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "lock_not_acquired"}
