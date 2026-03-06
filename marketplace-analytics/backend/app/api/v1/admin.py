"""Admin endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.config import Settings
from app.core.deps import (
    get_admin_request_context,
    get_app_settings,
    get_ch_client,
    require_admin_api_key,
)
from app.models.admin import (
    ActionQueueResponse,
    AdminRequestContext,
    BackfillRequest,
    BuildMartsBackfillRequest,
    BuildMartsRecentRequest,
    PruneOldRawRequest,
    RunAutomationRulesRequest,
    TransformBackfillRequest,
    TransformRecentRequest,
)
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_api_key)])


@router.get("/watermarks")
def get_watermarks(
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> dict[str, object]:
    service = AdminService(client, settings)
    items = service.watermarks()
    service.audit_read(action="watermarks", audit=audit, details={"items": len(items)})
    return {"items": items}


@router.post("/backfill", response_model=ActionQueueResponse)
def backfill(
    payload: BackfillRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_backfill(payload=payload, audit=audit)


@router.post("/transforms/recent", response_model=ActionQueueResponse)
def transform_recent(
    payload: TransformRecentRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_transform_recent(payload, audit)


@router.post("/transforms/backfill", response_model=ActionQueueResponse)
def transform_backfill(
    payload: TransformBackfillRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_transform_backfill(payload, audit)


@router.post("/marts/recent", response_model=ActionQueueResponse)
def marts_recent(
    payload: BuildMartsRecentRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_marts_recent(payload, audit)


@router.post("/marts/backfill", response_model=ActionQueueResponse)
def marts_backfill(
    payload: BuildMartsBackfillRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_marts_backfill(payload, audit)


@router.post("/maintenance/run-automation", response_model=ActionQueueResponse)
def run_automation(
    payload: RunAutomationRulesRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_run_automation_rules(payload, audit)


@router.post("/maintenance/prune-raw", response_model=ActionQueueResponse)
def prune_raw(
    payload: PruneOldRawRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_prune_old_raw(payload, audit)


@router.get("/task-runs")
def task_runs(
    limit: int = Query(default=200, ge=1, le=2000),
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
    audit: AdminRequestContext = Depends(get_admin_request_context),
) -> dict[str, object]:
    service = AdminService(client, settings)
    items = service.task_runs(limit=limit)
    service.audit_read(
        action="task_runs",
        audit=audit,
        details={"limit": limit, "items": len(items)},
    )
    return {"items": items}
