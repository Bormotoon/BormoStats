"""Produce CSV exports requested through the API (see common/exports.py)."""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from app.utils.celery_helpers import shared_task
from app.utils.events import emit_event
from app.utils.runtime import get_ch_client
from clickhouse_connect.driver import Client

from common.exports import (
    DATASETS,
    DATE_RANGE_DATASETS,
    EXPORT_RETENTION_DAYS,
    EXPORT_TASK,
    JOB_COLS,
    JOB_INSERT,
    MAX_EXPORT_ROWS,
    QUERIES_DIR,
    export_dir,
    export_path,
)

LOGGER = structlog.get_logger(__name__)
PRUNE_TASK = "tasks.exports.prune_exports"
DEFAULT_WINDOW_DAYS = 30


def _load_job(client: Client, organization_id: str, export_id: str) -> dict[str, Any] | None:
    rows = client.query(
        f"SELECT {JOB_COLS} FROM sys_export_jobs FINAL"
        " WHERE organization_id = {oid:String} AND export_id = {eid:String} LIMIT 1",
        parameters={"oid": organization_id, "eid": export_id},
    )
    for row in rows.named_results():
        return dict(row)
    return None


def _save_job(client: Client, job: dict[str, Any], **changes: Any) -> None:
    job.update(changes)
    job["updated_at"] = datetime.now(UTC).replace(microsecond=0)
    client.command(JOB_INSERT, parameters={name: job[name] for name in _job_fields()})


def _job_fields() -> tuple[str, ...]:
    return tuple(name.strip() for name in JOB_COLS.split(","))


def build_query_parameters(
    dataset: str, organization_id: str, raw: dict[str, Any]
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "organization_id": organization_id,
        "marketplace": raw.get("marketplace") or "",
        "account_id": raw.get("account_id") or "",
        "limit": MAX_EXPORT_ROWS,
        "offset": 0,
    }
    if dataset in DATE_RANGE_DATASETS:
        date_to = date.fromisoformat(raw["date_to"]) if raw.get("date_to") else date.today()
        date_from = (
            date.fromisoformat(raw["date_from"])
            if raw.get("date_from")
            else date_to - timedelta(days=DEFAULT_WINDOW_DAYS)
        )
        params.update(date_from=date_from, date_to=date_to)
    return params


def write_csv(
    client: Client, sql: str, parameters: dict[str, Any], target: os.PathLike[str]
) -> int:
    """Stream query rows into ``target`` (UTF-8 with BOM so Excel opens it correctly)."""
    rows_written = 0
    # The header comes from a zero-row probe: a streamed empty result carries no columns.
    header = client.query(f"SELECT * FROM ({sql}) LIMIT 0", parameters=parameters).column_names
    with (
        client.query_rows_stream(sql, parameters=parameters) as stream,
        open(target, "w", encoding="utf-8-sig", newline="") as handle,
    ):
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in stream:
            writer.writerow(row)
            rows_written += 1
    return rows_written


@shared_task(name=EXPORT_TASK)
def run_export(organization_id: str, export_id: str) -> dict[str, object]:
    client = get_ch_client()
    job = _load_job(client, organization_id, export_id)
    if job is None or job["status"] not in {"queued", "failed"}:
        return {"export_id": export_id, "status": "skipped"}

    _save_job(client, job, status="running", error="")
    target = export_path(organization_id, export_id)
    partial = target.with_suffix(".csv.part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        dataset = str(job["dataset"])
        sql = (QUERIES_DIR / DATASETS[dataset]).read_text(encoding="utf-8")
        parameters = build_query_parameters(
            dataset, organization_id, json.loads(job["params_json"] or "{}")
        )
        started = time.perf_counter()
        rows = write_csv(client, sql, parameters, partial)
        partial.replace(target)
        _save_job(client, job, status="done", row_count=rows, file_name=target.name)
        LOGGER.info(
            "export_done",
            export_id=export_id,
            dataset=dataset,
            rows=rows,
            seconds=round(time.perf_counter() - started, 2),
        )
    except Exception as exc:
        partial.unlink(missing_ok=True)
        _save_job(client, job, status="failed", error=str(exc)[:500])
        LOGGER.exception("export_failed", export_id=export_id)
        raise
    emit_event(
        organization_id,
        "export.completed",
        {"export_id": export_id, "dataset": job["dataset"], "rows": rows},
    )
    return {"export_id": export_id, "status": "done", "rows": rows}


@shared_task(name=PRUNE_TASK)
def prune_exports() -> dict[str, int]:
    cutoff = time.time() - EXPORT_RETENTION_DAYS * 86400
    removed = 0
    root = export_dir()
    if root.is_dir():
        for path in root.glob("*/*.csv*"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
    return {"removed": removed}
