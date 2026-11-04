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
    base = queries_dir.resolve()
    target = (queries_dir / name).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path traversal detected in query template name: {name}")
    if _app_env() == "dev":
        return target.read_text(encoding="utf-8")
    return _read_sql_cached(str(target))


def clear_sql_cache() -> None:
    _read_sql_cached.cache_clear()
