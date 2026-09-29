"""SQL building helpers shared by the backend and workers."""

from __future__ import annotations

from collections.abc import Sequence


def insert_values_sql(table: str, columns: Sequence[tuple[str, str]]) -> str:
    """Build ``INSERT ... VALUES`` with one server-side bind per column.

    Each bind is named after its column, so callers pass ``parameters`` keyed by
    column name. Composing the statement here (instead of ``str.format`` over a
    template containing ``{name:Type}`` binds) keeps Python formatting away from
    ClickHouse placeholders.
    """
    column_list = ", ".join(name for name, _ in columns)
    binds = ", ".join(f"{{{name}:{ch_type}}}" for name, ch_type in columns)
    return f"INSERT INTO {table} ({column_list}) VALUES ({binds})"
