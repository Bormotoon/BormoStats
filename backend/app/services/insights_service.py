from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.insights import ActionableTask, TaskUpdate
from clickhouse_connect.driver import Client

_TASK_COLS = "task_id, organization_id, trigger_type, marketplace, account_id, product_id, campaign_id, title, description, priority, status, created_at, resolved_at"


class InsightsService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    def list_tasks(self, organization_id: str = "default", status: str | None = None) -> list[ActionableTask]:
        where = ["organization_id = %(oid)s"]
        params: dict[str, object] = {"oid": organization_id}
        if status:
            where.append("status = %(status)s")
            params["status"] = status
        clause = " WHERE " + " AND ".join(where)
        rows = self._ch.query(
            f"SELECT {_TASK_COLS} FROM dim_actionable_task FINAL" + clause + " ORDER BY created_at DESC",
            parameters=params,
        )
        return [_row_to_task(r) for r in rows.named_results()]

    def update_task(self, task_id: str, data: TaskUpdate) -> ActionableTask | None:
        rows = self._ch.query(
            f"SELECT {_TASK_COLS} FROM dim_actionable_task FINAL WHERE task_id = {{tid:String}}",
            parameters={"tid": task_id},
        )
        existing = None
        for r in rows.named_results():
            existing = _row_to_task(r)
        if existing is None:
            return None
        now = datetime.utcnow()
        resolved = now if data.status == "resolved" else existing.resolved_at
        self._ch.command(
            "INSERT INTO dim_actionable_task ({cols})"
            " VALUES ({tid:String}, {oid:String}, {tt:String}, {mp:String}, {aid:String},"
            " {pid:Nullable(String)}, {cid:Nullable(String)}, {title:String}, {desc:String},"
            " {prio:String}, {status:String}, {created:DateTime}, {resolved:Nullable(DateTime)})".format(
                cols=_TASK_COLS
            ),
            parameters={
                "tid": existing.task_id,
                "oid": existing.organization_id,
                "tt": existing.trigger_type,
                "mp": existing.marketplace,
                "aid": existing.account_id,
                "pid": existing.product_id,
                "cid": existing.campaign_id,
                "title": existing.title,
                "desc": existing.description,
                "prio": existing.priority,
                "status": data.status,
                "created": existing.created_at or now,
                "resolved": resolved,
            },
        )
        return ActionableTask(
            task_id=existing.task_id,
            organization_id=existing.organization_id,
            trigger_type=existing.trigger_type,
            marketplace=existing.marketplace,
            account_id=existing.account_id,
            product_id=existing.product_id,
            campaign_id=existing.campaign_id,
            title=existing.title,
            description=existing.description,
            priority=existing.priority,
            status=data.status,
            created_at=existing.created_at or now,
            resolved_at=resolved,
        )


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
        created_at=r.get("created_at"),
        resolved_at=r.get("resolved_at"),
    )
