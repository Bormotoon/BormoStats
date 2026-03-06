"""ClickHouse client helpers."""

from __future__ import annotations

from typing import Any

import clickhouse_connect
from app.core.config import Settings


def build_client(settings: Settings) -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=settings.ch_host,
        port=settings.ch_port,
        username=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_db,
        autogenerate_session_id=False,
    )


def query_dicts(
    client: clickhouse_connect.driver.Client,
    sql: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = client.query(sql, parameters=parameters or {})
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]
