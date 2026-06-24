"""Admin endpoints."""

from __future__ import annotations

from app.core.deps import (
    AdminRequestContextDependency,
    ChClientDependency,
    SettingsDependency,
    require_admin_api_key,
)
from app.models.admin import (
    ActionQueueResponse,
    BackfillRequest,
    BuildMartsBackfillRequest,
    BuildMartsRecentRequest,
    PruneOldRawRequest,
    RunAutomationRulesRequest,
    TransformBackfillRequest,
    TransformRecentRequest,
)
from app.services.admin_service import AdminService
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_api_key)])


@router.get("/watermarks")
def get_watermarks(
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> dict[str, object]:
    service = AdminService(client, settings)
    items = service.watermarks()
    service.audit_read(action="watermarks", audit=audit, details={"items": len(items)})
    return {"items": items}


@router.post("/backfill", response_model=ActionQueueResponse)
def backfill(
    payload: BackfillRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_backfill(payload=payload, audit=audit)


@router.post("/transforms/recent", response_model=ActionQueueResponse)
def transform_recent(
    payload: TransformRecentRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_transform_recent(payload, audit)


@router.post("/transforms/backfill", response_model=ActionQueueResponse)
def transform_backfill(
    payload: TransformBackfillRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_transform_backfill(payload, audit)


@router.post("/marts/recent", response_model=ActionQueueResponse)
def marts_recent(
    payload: BuildMartsRecentRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_marts_recent(payload, audit)


@router.post("/marts/backfill", response_model=ActionQueueResponse)
def marts_backfill(
    payload: BuildMartsBackfillRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_marts_backfill(payload, audit)


@router.post("/maintenance/run-automation", response_model=ActionQueueResponse)
def run_automation(
    payload: RunAutomationRulesRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_run_automation_rules(payload, audit)


@router.post("/maintenance/prune-raw", response_model=ActionQueueResponse)
def prune_raw(
    payload: PruneOldRawRequest,
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> ActionQueueResponse:
    service = AdminService(client, settings)
    return service.queue_prune_old_raw(payload, audit)


@router.get("/task-runs")
def task_runs(
    *,
    limit: int = Query(default=200, ge=1, le=2000),
    client: ChClientDependency,
    settings: SettingsDependency,
    audit: AdminRequestContextDependency,
) -> dict[str, object]:
    service = AdminService(client, settings)
    items = service.task_runs(limit=limit)
    service.audit_read(
        action="task_runs",
        audit=audit,
        details={"limit": limit, "items": len(items)},
    )
    return {"items": items}
