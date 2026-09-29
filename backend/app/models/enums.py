"""Enum helpers shared by API models."""

from __future__ import annotations

from enum import IntEnum
from typing import Self


class ClickHouseIntEnum(IntEnum):
    """IntEnum mapped to a ClickHouse ``Enum8`` column.

    ClickHouse returns enum values by name (``'admin'``) while API payloads use the
    numeric value, so row mappers go through :meth:`parse` to accept both.
    """

    @classmethod
    def parse(cls, value: object) -> Self:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.lstrip("-").isdigit():
                return cls(int(stripped))
            try:
                return cls[stripped]
            except KeyError as exc:
                raise ValueError(f"{stripped!r} is not a valid {cls.__name__}") from exc
        if isinstance(value, int):
            return cls(value)
        raise ValueError(f"{value!r} is not a valid {cls.__name__}")
