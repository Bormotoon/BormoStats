"""Asynchronous CSV exports: jobs are queued here and produced by tasks.exports."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.db.ch import utc_now
from app.models.exports import ExportJob, ExportRequest
from app.services.task_queue import send_task
from clickhouse_connect.driver import Client

from common.exports import EXPORT_TASK, JOB_COLS, JOB_INSERT, export_path


class ExportService:
    def __init__(self, ch: Client, settings: Settings, organization_id: str) -> None:
        self._ch = ch
        self._settings = settings
        self._org = organization_id

    def create(
        self,
        request: ExportRequest,
        requested_by: str,
        *,
        include_costs: bool = False,
    ) -> ExportJob:
        now = utc_now()
        job = ExportJob(
            export_id=str(uuid.uuid4()),
            organization_id=self._org,
            requested_by=requested_by,
            dataset=request.dataset,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        params = request.model_dump(mode="json", exclude={"dataset"})
        params["include_costs"] = bool(include_costs)
        self._ch.command(
            JOB_INSERT,
            parameters={
                **job.model_dump(),
                "params_json": json.dumps(params, ensure_ascii=False),
                "file_name": "",
            },
        )
        send_task(
            self._settings,
            EXPORT_TASK,
            kwargs={"organization_id": self._org, "export_id": job.export_id},
        )
        return job

    def list_jobs(self, limit: int = 50) -> list[ExportJob]:
        rows = self._ch.query(
            f"SELECT {JOB_COLS} FROM sys_export_jobs FINAL WHERE organization_id = {{oid:String}}"
            " ORDER BY created_at DESC LIMIT {lim:UInt32}",
            parameters={"oid": self._org, "lim": limit},
        )
        return [_row_to_job(r) for r in rows.named_results()]

    def get(self, export_id: str) -> ExportJob | None:
        rows = self._ch.query(
            f"SELECT {JOB_COLS} FROM sys_export_jobs FINAL"
            " WHERE organization_id = {oid:String} AND export_id = {eid:String} LIMIT 1",
            parameters={"oid": self._org, "eid": export_id},
        )
        for r in rows.named_results():
            return _row_to_job(r)
        return None

    def file_for(self, job: ExportJob) -> Path | None:
        if job.status != "done":
            return None
        path = export_path(self._org, job.export_id)
        return path if path.is_file() else None


def _row_to_job(r: dict[str, Any]) -> ExportJob:
    return ExportJob(**{k: r[k] for k in ExportJob.model_fields if k in r})
