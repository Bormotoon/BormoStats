from __future__ import annotations

from functools import cache
from pathlib import Path


@cache
def _read_sql_cached(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_sql(sql_dir: Path, name: str) -> str:
    path = sql_dir / name
    return _read_sql_cached(str(path))


def clear_sql_cache() -> None:
    _read_sql_cached.cache_clear()
