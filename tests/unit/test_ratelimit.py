from __future__ import annotations

from app.core.ratelimit import ClientBuckets


def test_buckets_are_per_client_and_bounded() -> None:
    buckets = ClientBuckets(rate=0.0, burst=2, max_clients=2)
    assert buckets.consume("a") and buckets.consume("a")
    assert not buckets.consume("a")
    # another client still has its own budget
    assert buckets.consume("b")
    buckets.consume("c")  # evicts the least recently used client ("a")
    assert buckets.consume("a")
