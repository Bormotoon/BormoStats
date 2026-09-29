"""Export job contract shared by the API (enqueue/download) and workers (produce)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from common.sql import insert_values_sql

EXPORT_TASK = "tasks.exports.run_export"
MAX_EXPORT_ROWS = 1_000_000
EXPORT_RETENTION_DAYS = 7
DATASETS: dict[str, str] = {
    # dataset -> SQL file under backend/app/db/queries (client-side %(name)s params)
    "sales_daily": "sales.sql",
    "stocks_current": "stocks.sql",
    "funnel_daily": "funnel.sql",
    "ads_daily": "ads.sql",
    "kpis": "kpis.sql",
}
DATE_RANGE_DATASETS = frozenset({"sales_daily", "funnel_daily", "ads_daily"})
JOB_COLUMNS: tuple[tuple[str, str], ...] = (
    ("export_id", "String"),
    ("organization_id", "String"),
    ("requested_by", "String"),
    ("dataset", "String"),
    ("params_json", "String"),
    ("status", "String"),
    ("row_count", "UInt64"),
    ("file_name", "String"),
    ("error", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
JOB_COLS = ", ".join(name for name, _ in JOB_COLUMNS)
JOB_INSERT = insert_values_sql("sys_export_jobs", JOB_COLUMNS)
QUERIES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "db" / "queries"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def export_dir() -> Path:
    return Path(os.getenv("EXPORT_DIR", "/tmp/bormostats-exports"))


def export_path(organization_id: str, export_id: str) -> Path:
    """Location of an export file; ids are validated so paths cannot escape EXPORT_DIR."""
    if not _SAFE_ID.fullmatch(organization_id) or not _SAFE_ID.fullmatch(export_id):
        raise ValueError("invalid export identifier")
    return export_dir() / organization_id / f"{export_id}.csv"
