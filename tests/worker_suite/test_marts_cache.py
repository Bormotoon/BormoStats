from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest
from app.tasks import marts

from common.query_cache import GENERATION_KEY
from tests.fakes import FakeClickHouse


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]


def _patch(monkeypatch: pytest.MonkeyPatch, ch: Any, redis_client: FakeRedis) -> None:
    monkeypatch.setattr(marts, "get_ch_client", lambda: ch)
    monkeypatch.setattr(marts, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(marts, "rebuild_task_scope", lambda **_: nullcontext())
    monkeypatch.setattr(marts, "log_task_run", lambda *args, **kwargs: None)


def test_successful_mart_build_invalidates_api_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = FakeRedis()
    _patch(monkeypatch, FakeClickHouse(), redis_client)

    assert marts.build_marts_recent()["status"] == "success"
    assert redis_client.values[GENERATION_KEY] == 1


def test_failed_mart_build_keeps_api_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClickHouse(FakeClickHouse):
        def command(self, sql: str, parameters: dict[str, Any] | None = None, **_: Any) -> None:
            raise RuntimeError("clickhouse is down")

    redis_client = FakeRedis()
    _patch(monkeypatch, FailingClickHouse(), redis_client)

    with pytest.raises(RuntimeError):
        marts.build_marts_recent()
    assert GENERATION_KEY not in redis_client.values
