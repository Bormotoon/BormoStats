"""ClickHouse client helpers."""

from __future__ import annotations

from typing import Any

import clickhouse_connect
from app.core.config import Settings
from clickhouse_connect.driver.httputil import get_pool_manager

DEFAULT_CH_POOL_MAXSIZE = 16


def build_raw_client(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
    pool_maxsize: int = DEFAULT_CH_POOL_MAXSIZE,
) -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
        pool_mgr=get_pool_manager(maxsize=max(1, pool_maxsize)),
        autogenerate_session_id=False,
    )


def build_client(settings: Settings) -> clickhouse_connect.driver.Client:
    return build_raw_client(
        host=settings.ch_host,
        port=settings.ch_port,
        username=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_db,
        pool_maxsize=settings.ch_pool_maxsize,
    )


def query_dicts(
    client: clickhouse_connect.driver.Client,
    sql: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = client.query(sql, parameters=parameters or {})
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]
