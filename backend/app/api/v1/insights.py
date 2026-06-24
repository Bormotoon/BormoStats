from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import (
    ChClientDependency,
    CurrentUserDependency,
    require_admin_key_or_org_role,
)
from app.models.insights import ActionableTask, TaskUpdate
from app.models.organization import OrgMemberRole
from app.services.insights_service import InsightsService
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter(prefix="/insights", tags=["insights"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> InsightsService:
    return InsightsService(ch)


@router.get("/tasks")
def list_tasks(
    ch: ChClientDependency,
    current_user: CurrentUserDependency,
    status: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.viewer)),
) -> list[ActionableTask]:
    return _svc(ch).list_tasks(organization_id=current_user.organization_id, status=status)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    body: TaskUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> ActionableTask:
    task = _svc(ch).update_task(task_id, body)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task
