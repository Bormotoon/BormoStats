"""ClickHouse client helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import clickhouse_connect
from app.core.config import Settings
from clickhouse_connect.driver.httputil import get_pool_manager

from common.sql import insert_values_sql

__all__ = [
    "PARTITION_LOCAL_FINAL",
    "build_client",
    "build_raw_client",
    "insert_values_sql",
    "query_dicts",
    "utc_now",
]

DEFAULT_CH_POOL_MAXSIZE = 16
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_QUERY_TIMEOUT_SECONDS = 30


def build_raw_client(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
    pool_maxsize: int = DEFAULT_CH_POOL_MAXSIZE,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    query_timeout: int = DEFAULT_QUERY_TIMEOUT_SECONDS,
) -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
        pool_mgr=get_pool_manager(maxsize=max(1, pool_maxsize)),
        autogenerate_session_id=False,
        connect_timeout=connect_timeout,
        # the HTTP read timeout is slightly above the server-side limit so the
        # server reports the timeout instead of the socket being cut mid-query
        send_receive_timeout=query_timeout + 5,
        settings={"max_execution_time": query_timeout},
    )


def build_client(settings: Settings) -> clickhouse_connect.driver.Client:
    return build_raw_client(
        host=settings.ch_host,
        port=settings.ch_port,
        username=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_db,
        pool_maxsize=settings.ch_pool_maxsize,
        connect_timeout=getattr(
            settings, "ch_connect_timeout_seconds", DEFAULT_CONNECT_TIMEOUT_SECONDS
        ),
        query_timeout=getattr(settings, "ch_query_timeout_seconds", DEFAULT_QUERY_TIMEOUT_SECONDS),
    )


def query_dicts(
    client: clickhouse_connect.driver.Client,
    sql: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = client.query(sql, parameters=parameters or {})
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


# For ReplacingMergeTree marts partitioned by a function of a sorting-key column
# (e.g. PARTITION BY toYYYYMM(day), ORDER BY (day, ...)), rows with the same key always
# live in one partition, so FINAL may skip cross-partition merging. Do NOT use it for
# tables partitioned by a column outside the sorting key (e.g. raw_* by ingestion time).
PARTITION_LOCAL_FINAL: dict[str, int] = {"do_not_merge_across_partitions_select_final": 1}


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp truncated to ClickHouse ``DateTime`` precision."""
    return datetime.now(UTC).replace(microsecond=0)
