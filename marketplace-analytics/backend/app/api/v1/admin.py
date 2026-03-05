"""Admin endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.deps import get_app_settings, get_ch_client, require_admin_api_key
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_api_key)])


class RunTaskRequest(BaseModel):
    task_name: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class BackfillRequest(BaseModel):
    marketplace: str
    dataset: str
    days: int = Field(default=14, ge=1, le=365)


@router.get("/watermarks")
def get_watermarks(
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    service = AdminService(client, settings)
    return {"items": service.watermarks()}


@router.post("/run-task")
def run_task(
    payload: RunTaskRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    service = AdminService(client, settings)
    return service.run_task(task_name=payload.task_name, args=payload.args, kwargs=payload.kwargs)


@router.post("/backfill")
def backfill(
    payload: BackfillRequest,
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    service = AdminService(client, settings)
    try:
        return service.backfill(
            marketplace=payload.marketplace,
            dataset=payload.dataset,
            days=payload.days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/task-runs")
def task_runs(
    limit: int = Query(default=200, ge=1, le=2000),
    client=Depends(get_ch_client),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    service = AdminService(client, settings)
    return {"items": service.task_runs(limit=limit)}
