"""Shared SQL template loader with production caching."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path


def _app_env() -> str:
    return os.getenv("APP_ENV", "dev").strip().lower()


@cache
def _read_sql_cached(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_sql(queries_dir: Path, name: str) -> str:
    path = queries_dir / name
    if _app_env() == "dev":
        return path.read_text(encoding="utf-8")
    return _read_sql_cached(str(path))


def clear_sql_cache() -> None:
    _read_sql_cached.cache_clear()
