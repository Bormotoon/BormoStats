"""Redis read-through cache for analytics queries."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from app.core.config import get_settings
from app.core.deps import get_ch_client, get_query_cache, open_query_cache
from app.main import app
from app.services import query_cache as query_cache_module
from app.services.query_cache import QueryCache
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from common.query_cache import GENERATION_KEY, KEY_PREFIX, bump_generation
from tests.fakes import FakeClickHouse

ADMIN_HEADERS = {"X-API-Key": "test-admin-key"}


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.calls = 0

    def mget(self, keys: list[str]) -> list[bytes | None]:
        self.calls += 1
        return [self.values.get(key) for key in keys]

    def set(self, key: str, value: str, ex: int) -> bool:
        self.calls += 1
        self.values[key] = value.encode()
        self.ttls[key] = ex
        return True

    def incr(self, key: str) -> int:
        self.calls += 1
        value = int(self.values.get(key, b"0")) + 1
        self.values[key] = str(value).encode()
        return value

    def close(self) -> None:
        return None


class BrokenRedis(FakeRedis):
    def mget(self, keys: list[str]) -> list[bytes | None]:
        self.calls += 1
        raise RedisConnectionError("redis is down")


def _cache(redis_client: FakeRedis, **overrides: int) -> QueryCache:
    options = {"ttl_seconds": 300, "max_entry_bytes": 1_000_000, **overrides}
    return QueryCache(redis_client, **options)  # type: ignore[arg-type]


class Counter:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls = 0

    def __call__(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.rows


PARAMS = {"organization_id": "org-a", "date_from": date(2026, 9, 1), "limit": 10}


def test_second_lookup_is_served_from_redis_with_ttl() -> None:
    redis_client = FakeRedis()
    cache = _cache(redis_client)
    compute = Counter([{"day": date(2026, 9, 1), "revenue": Decimal("10.5")}])

    first = cache.get_or_compute("sales.sql", PARAMS, compute)
    second = cache.get_or_compute("sales.sql", PARAMS, compute)

    assert compute.calls == 1
    # A miss returns the same JSON-compatible values a hit does.
    assert first == second == [{"day": "2026-09-01", "revenue": 10.5}]
    [key] = [k for k in redis_client.values if k != GENERATION_KEY]
    assert key.startswith(f"{KEY_PREFIX}:entry:")
    assert redis_client.ttls[key] == 300


def test_entries_are_keyed_by_query_and_organization() -> None:
    cache = _cache(FakeRedis())
    compute = Counter([{"x": 1}])

    cache.get_or_compute("sales.sql", PARAMS, compute)
    cache.get_or_compute("sales.sql", {**PARAMS, "organization_id": "org-b"}, compute)
    cache.get_or_compute("ads.sql", PARAMS, compute)

    assert compute.calls == 3


def test_generation_bump_invalidates_existing_entries() -> None:
    redis_client = FakeRedis()
    cache = _cache(redis_client)
    compute = Counter([{"x": 1}])

    cache.get_or_compute("sales.sql", PARAMS, compute)
    assert bump_generation(redis_client) == 1
    cache.get_or_compute("sales.sql", PARAMS, compute)
    cache.get_or_compute("sales.sql", PARAMS, compute)

    assert compute.calls == 2


def test_corrupted_entry_is_treated_as_a_miss() -> None:
    redis_client = FakeRedis()
    cache = _cache(redis_client)
    compute = Counter([{"x": 1}])
    cache.get_or_compute("sales.sql", PARAMS, compute)
    [key] = [k for k in redis_client.values if k != GENERATION_KEY]
    redis_client.values[key] = b"not json"

    assert cache.get_or_compute("sales.sql", PARAMS, compute) == [{"x": 1}]
    assert compute.calls == 2
    assert json.loads(redis_client.values[key])["rows"] == [{"x": 1}]


def test_oversized_results_are_served_but_not_stored() -> None:
    redis_client = FakeRedis()
    cache = _cache(redis_client, max_entry_bytes=64)
    compute = Counter([{"payload": "x" * 100}])

    assert cache.get_or_compute("sales.sql", PARAMS, compute) == compute.rows
    assert cache.get_or_compute("sales.sql", PARAMS, compute) == compute.rows
    assert compute.calls == 2
    assert redis_client.values == {}


def test_redis_outage_falls_back_to_clickhouse_and_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(query_cache_module.time, "monotonic", lambda: clock["now"])
    redis_client = BrokenRedis()
    cache = _cache(redis_client)
    compute = Counter([{"x": 1}])

    assert cache.get_or_compute("sales.sql", PARAMS, compute) == [{"x": 1}]
    assert cache.get_or_compute("sales.sql", PARAMS, compute) == [{"x": 1}]
    assert redis_client.calls == 1  # the second lookup skipped Redis entirely

    clock["now"] += 31
    cache.get_or_compute("sales.sql", PARAMS, compute)
    assert redis_client.calls == 2
    assert compute.calls == 3


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeClickHouse, FakeRedis]]:
    ch = FakeClickHouse().on("mrt_sales_daily", [{"day": "2026-09-01", "revenue": 10.0}])
    redis_client = FakeRedis()
    cache = _cache(redis_client)
    app.dependency_overrides[get_ch_client] = lambda: ch
    app.dependency_overrides[get_query_cache] = lambda: cache
    try:
        with TestClient(app, headers=ADMIN_HEADERS) as client:
            yield client, ch, redis_client
    finally:
        app.dependency_overrides.clear()


def _sales_queries(ch: FakeClickHouse) -> int:
    return sum("mrt_sales_daily" in sql for sql, _ in ch.queries)


def test_analytics_endpoint_reuses_cached_rows(
    api: tuple[TestClient, FakeClickHouse, FakeRedis],
) -> None:
    client, ch, _ = api
    params = {"date_from": "2026-09-01", "date_to": "2026-09-07"}

    first = client.get("/api/v1/sales/daily", params=params)
    second = client.get("/api/v1/sales/daily", params=params)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["items"] == [{"day": "2026-09-01", "revenue": 10.0}]
    assert _sales_queries(ch) == 1

    client.get("/api/v1/sales/daily", params={**params, "date_to": "2026-09-08"})
    assert _sales_queries(ch) == 2


def test_account_reassignment_invalidates_analytics(
    api: tuple[TestClient, FakeClickHouse, FakeRedis],
) -> None:
    client, _, redis_client = api

    response = client.post(
        "/api/v1/organizations/default/accounts",
        json={"account_id": "shop-1", "marketplace": "wb", "title": "Shop"},
    )

    assert response.status_code == 201, response.text
    assert redis_client.values[GENERATION_KEY] == b"1"


def test_cache_is_disabled_when_ttl_is_zero() -> None:
    settings = get_settings()
    assert settings.query_cache_ttl_seconds == 0
    assert open_query_cache(app, settings) is None
