"""Test doubles shared by unit tests."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

Rows = list[dict[str, Any]]
Responder = Callable[[str, dict[str, Any]], Rows | None]

_SERVER_BIND = re.compile(r"\{(\w+):([^{}]+)\}")


class FakeResult:
    def __init__(self, rows: Rows) -> None:
        self._rows = rows
        self.column_names: tuple[str, ...] = tuple(rows[0].keys()) if rows else ()
        self.result_rows = [tuple(row.values()) for row in rows]

    def named_results(self) -> Iterator[dict[str, Any]]:
        return iter([dict(row) for row in self._rows])


@dataclass
class FakeClickHouse:
    """Records every statement; ``responders`` answer queries by returning rows.

    Each responder gets ``(sql, parameters)`` and returns rows or ``None`` to pass.
    Server-side binds are checked: every ``{name:Type}`` placeholder must have a
    parameter, which catches ``str.format`` mistakes like the old C-03/C-04 bugs.
    """

    responders: list[Responder] = field(default_factory=list)
    queries: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    commands: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    inserts: list[tuple[str, list[list[Any]], list[str]]] = field(default_factory=list)

    def on(self, needle: str, rows: Rows) -> FakeClickHouse:
        self.responders.append(lambda sql, _params: rows if needle in sql else None)
        return self

    @staticmethod
    def _check_binds(sql: str, parameters: dict[str, Any]) -> None:
        missing = {name for name, _ in _SERVER_BIND.findall(sql)} - set(parameters)
        if missing:
            raise AssertionError(f"unbound server-side parameters {sorted(missing)} in: {sql}")

    def query(self, sql: str, parameters: dict[str, Any] | None = None, **_: Any) -> FakeResult:
        params = dict(parameters or {})
        self._check_binds(sql, params)
        self.queries.append((sql, params))
        for responder in self.responders:
            rows = responder(sql, params)
            if rows is not None:
                return FakeResult(rows)
        return FakeResult([])

    def command(self, sql: str, parameters: dict[str, Any] | None = None, **_: Any) -> None:
        params = dict(parameters or {})
        self._check_binds(sql, params)
        self.commands.append((sql, params))

    def insert(
        self,
        table: str,
        data: Sequence[Sequence[Any]],
        column_names: Sequence[str] = (),
        **_: Any,
    ) -> None:
        self.inserts.append((table, [list(row) for row in data], list(column_names)))

    def close(self) -> None:
        return None

    def commands_matching(self, needle: str) -> list[tuple[str, dict[str, Any]]]:
        return [(sql, params) for sql, params in self.commands if needle in sql]
