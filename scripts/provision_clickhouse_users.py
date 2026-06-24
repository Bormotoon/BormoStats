#!/usr/bin/env python3
"""Provision ClickHouse database and application users."""

from __future__ import annotations

import os
import re

import clickhouse_connect

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_identifier(label: str, value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise SystemExit(f"Invalid {label} identifier: {value}")
    return value


def provision_clickhouse_users() -> None:
    db_name = _require_identifier("APP_CH_DB", os.getenv("APP_CH_DB", "mp_analytics"))
    app_user = _require_identifier("APP_CH_USER", os.getenv("APP_CH_USER", ""))
    app_password = os.getenv("APP_CH_PASSWORD", "")
    ro_user = os.getenv("APP_CH_RO_USER", "")
    ro_password = os.getenv("APP_CH_RO_PASSWORD", "")

    client = clickhouse_connect.get_client(
        host=os.getenv("CH_HOST", "localhost"),
        port=int(os.getenv("CH_PORT", "8123")),
        username=os.getenv("CH_USER", "default"),
        password=os.getenv("CH_PASSWORD", ""),
        database="default",
    )
    try:
        quoted_db = f"`{db_name}`"
        quoted_app_user = f"`{app_user}`"
        create_app_user_sql = (
            f"CREATE USER IF NOT EXISTS {quoted_app_user} "
            "IDENTIFIED WITH plaintext_password BY %(password)s"
        )
        client.command(f"CREATE DATABASE IF NOT EXISTS {quoted_db}")
        client.command(
            create_app_user_sql,
            parameters={"password": app_password},
        )
        client.command(f"GRANT ALL ON {quoted_db}.* TO {quoted_app_user}")

        if ro_user or ro_password:
            ro_user_value = _require_identifier("APP_CH_RO_USER", ro_user)
            quoted_ro_user = f"`{ro_user_value}`"
            create_ro_user_sql = (
                f"CREATE USER IF NOT EXISTS {quoted_ro_user} "
                "IDENTIFIED WITH plaintext_password BY %(password)s"
            )
            client.command(
                create_ro_user_sql,
                parameters={"password": ro_password},
            )
            client.command(f"GRANT SELECT ON {quoted_db}.* TO {quoted_ro_user}")
    finally:
        client.close()


if __name__ == "__main__":
    provision_clickhouse_users()
