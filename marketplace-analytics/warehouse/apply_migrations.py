#!/usr/bin/env python3
"""Apply ClickHouse SQL migrations in lexical order."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path

import clickhouse_connect

LOGGER = logging.getLogger("warehouse.migrations")


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def split_sql_statements(sql: str) -> Iterable[str]:
    """Split SQL script into executable statements without breaking quoted strings."""
    statements: list[str] = []
    buffer: list[str] = []
    in_single = False
    in_double = False

    for char in sql:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double

        if char == ";" and not in_single and not in_double:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            continue

        buffer.append(char)

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)

    return statements


def ensure_sys_table(client: clickhouse_connect.driver.Client) -> None:
    client.command("CREATE DATABASE IF NOT EXISTS mp_analytics")
    client.command("""
        CREATE TABLE IF NOT EXISTS mp_analytics.sys_schema_migrations
        (
          version String,
          applied_at DateTime DEFAULT now()
        )
        ENGINE = MergeTree
        ORDER BY (version)
        """)


def load_applied_versions(client: clickhouse_connect.driver.Client) -> set[str]:
    result = client.query("SELECT version FROM mp_analytics.sys_schema_migrations")
    return {str(row[0]) for row in result.result_rows}


def apply_migrations() -> None:
    configure_logging()

    client = clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", ""),
        database=os.getenv("CH_DB", "mp_analytics"),
    )

    try:
        ensure_sys_table(client)
        applied_versions = load_applied_versions(client)

        migrations_dir = Path(__file__).resolve().parent / "migrations"
        migration_paths = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())

        LOGGER.info("migrations_found=%s", len(migration_paths))

        for migration_path in migration_paths:
            version = migration_path.stem
            if version in applied_versions:
                LOGGER.info("skip version=%s reason=already_applied", version)
                continue

            started_at = time.perf_counter()
            sql = migration_path.read_text(encoding="utf-8")

            try:
                for statement in split_sql_statements(sql):
                    client.command(statement)
                client.command(
                    "INSERT INTO mp_analytics.sys_schema_migrations (version) VALUES (%(version)s)",
                    parameters={"version": version},
                )
                duration = round(time.perf_counter() - started_at, 3)
                LOGGER.info("applied version=%s duration_s=%s", version, duration)
            except Exception:
                duration = round(time.perf_counter() - started_at, 3)
                LOGGER.exception("failed version=%s duration_s=%s", version, duration)
                raise
    finally:
        client.close()


if __name__ == "__main__":
    apply_migrations()
