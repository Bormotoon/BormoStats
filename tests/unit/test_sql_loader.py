from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import sql_loader  # noqa: E402


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    sql_loader.clear_sql_cache()
    yield
    sql_loader.clear_sql_cache()


def test_sql_loader_caches_disk_reads_outside_dev(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_path = tmp_path / "query.sql"
    query_path.write_text("SELECT 1", encoding="utf-8")
    reads = 0
    original_read_text = Path.read_text

    def spy_read_text(self: Path, *args: object, **kwargs: object) -> str:
        nonlocal reads
        reads += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr(Path, "read_text", spy_read_text)

    assert sql_loader.load_sql(tmp_path, "query.sql") == "SELECT 1"
    assert sql_loader.load_sql(tmp_path, "query.sql") == "SELECT 1"
    assert reads == 1


def test_sql_loader_keeps_hot_reload_behavior_in_dev(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_path = tmp_path / "query.sql"
    query_path.write_text("SELECT 1", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "dev")

    assert sql_loader.load_sql(tmp_path, "query.sql") == "SELECT 1"

    query_path.write_text("SELECT 2", encoding="utf-8")

    assert sql_loader.load_sql(tmp_path, "query.sql") == "SELECT 2"
