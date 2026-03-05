"""Shared runtime helpers for workers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import clickhouse_connect
from redis import Redis


def get_ch_client() -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", ""),
        database=os.getenv("CH_DB", "mp_analytics"),
    )


def get_redis_client() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def new_run_context(task_name: str) -> tuple[str, datetime]:
    _ = task_name
    return str(uuid4()), datetime.now(UTC)


def log_task_run(
    client: clickhouse_connect.driver.Client,
    task_name: str,
    run_id: str,
    started_at: datetime,
    status: str,
    rows_ingested: int,
    message: str,
    meta: dict[str, Any] | None = None,
) -> None:
    finished_at = datetime.now(UTC).replace(tzinfo=None)
    payload = meta or {}
    client.command(
        """
        INSERT INTO sys_task_runs
        (task_name, run_id, started_at, finished_at, status, rows_ingested, message, meta_json)
        VALUES (%(task_name)s, %(run_id)s, %(started_at)s, %(finished_at)s, %(status)s, %(rows_ingested)s, %(message)s, %(meta_json)s)
        """,
        parameters={
            "task_name": task_name,
            "run_id": run_id,
            "started_at": started_at.replace(tzinfo=None),
            "finished_at": finished_at,
            "status": status,
            "rows_ingested": rows_ingested,
            "message": message,
            "meta_json": json.dumps(payload, ensure_ascii=True),
        },
    )
