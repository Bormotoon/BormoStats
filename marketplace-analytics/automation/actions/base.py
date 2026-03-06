"""Automation action protocol."""

from __future__ import annotations

from typing import Any, Protocol


class Action(Protocol):
    """Action interface used by automation engine."""

    def execute(self, rule_name: str, payload: dict[str, Any], message: str) -> None: ...
