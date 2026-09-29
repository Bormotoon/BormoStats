"""Actionable insight tasks, scoped to one organization."""

from __future__ import annotations

from typing import Any

from app.db.ch import utc_now
from app.models.insights import ActionableTask, TaskUpdate
from clickhouse_connect.driver import Client

from common.insights import TASK_COLS as _TASK_COLS
from common.insights import TASK_INSERT

_CLOSED_STATUSES = frozenset({"resolved", "dismissed"})


class InsightsService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def list_tasks(self, status: str | None = None, limit: int = 500) -> list[ActionableTask]:
        where = ["organization_id = {oid:String}"]
        params: dict[str, object] = {"oid": self._org, "lim": limit}
        if status:
            where.append("status = {status:String}")
            params["status"] = status
        rows = self._ch.query(
            f"SELECT {_TASK_COLS} FROM dim_actionable_task FINAL"
            f" WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT {{lim:UInt32}}",
            parameters=params,
        )
        return [_row_to_task(r) for r in rows.named_results()]

    def get_task(self, task_id: str) -> ActionableTask | None:
        rows = self._ch.query(
            f"SELECT {_TASK_COLS} FROM dim_actionable_task FINAL"
            " WHERE organization_id = {oid:String} AND task_id = {tid:String} LIMIT 1",
            parameters={"oid": self._org, "tid": task_id},
        )
        for r in rows.named_results():
            return _row_to_task(r)
        return None

    def update_task(self, task_id: str, data: TaskUpdate) -> ActionableTask | None:
        existing = self.get_task(task_id)
        if existing is None:
            return None
        now = utc_now()
        # Re-opening a task clears resolved_at; closing it stamps the resolution time.
        closed = data.status in _CLOSED_STATUSES
        resolved_at = (existing.resolved_at or now) if closed else None
        task = existing.model_copy(
            update={
                "status": data.status,
                "resolved_at": resolved_at,
                "created_at": existing.created_at or now,
            }
        )
        self._ch.command(TASK_INSERT, parameters=task_parameters(task))
        return task


def task_parameters(task: ActionableTask) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "organization_id": task.organization_id,
        "trigger_type": task.trigger_type,
        "marketplace": task.marketplace,
        "account_id": task.account_id,
        "product_id": task.product_id,
        "campaign_id": task.campaign_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "dedupe_key": task.dedupe_key,
        "created_at": task.created_at,
        "resolved_at": task.resolved_at,
    }


def _row_to_task(r: dict[str, Any]) -> ActionableTask:
    return ActionableTask(
        task_id=r["task_id"],
        organization_id=r["organization_id"],
        trigger_type=r["trigger_type"],
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        product_id=r.get("product_id"),
        campaign_id=r.get("campaign_id"),
        title=r["title"],
        description=r["description"],
        priority=r["priority"],
        status=r["status"],
        dedupe_key=r.get("dedupe_key") or "",
        created_at=r.get("created_at"),
        resolved_at=r.get("resolved_at"),
    )
