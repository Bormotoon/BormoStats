from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import CatalogWriteAuth, ViewerAuth
from app.core.deps import ChClientDependency
from app.models.insights import TASK_STATUS_PATTERN, ActionableTask, TaskUpdate
from app.services.insights_service import InsightsService
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/insights", tags=["insights"], responses=API_ERROR_RESPONSES)


@router.get("/tasks")
def list_tasks(
    ch: ChClientDependency,
    auth: ViewerAuth,
    task_status: str | None = Query(default=None, alias="status", pattern=TASK_STATUS_PATTERN),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[ActionableTask]:
    return InsightsService(ch, auth.organization_id).list_tasks(status=task_status, limit=limit)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    body: TaskUpdate,
    ch: ChClientDependency,
    auth: CatalogWriteAuth,
) -> ActionableTask:
    task = InsightsService(ch, auth.organization_id).update_task(task_id, body)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task
