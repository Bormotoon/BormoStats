from __future__ import annotations

from datetime import UTC, datetime

from app.tasks.insights import (
    BAD_ADS_SQL,
    STAGNANT_SQL,
    TURNOVER_SQL,
    Recommendation,
    build_digest,
    insert_new_tasks,
)

from common.insights import dedupe_key
from tests.fakes import FakeClickHouse

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)


def _rec(product: str = "1") -> Recommendation:
    return Recommendation(
        trigger_type="turnover",
        marketplace="wb",
        account_id="default",
        product_id=product,
        campaign_id=None,
        title="t",
        description="d",
        priority="high",
    )


def test_trigger_sql_is_org_scoped_and_uses_days() -> None:
    for sql in (TURNOVER_SQL, STAGNANT_SQL, BAD_ADS_SQL):
        assert "organization_id = {oid:String}" in sql
        assert "now() - 14" not in sql and "now() - 1" not in sql
    # mrt_sales_daily has no stock column; stock comes from mrt_stock_daily
    assert "FROM mrt_stock_daily" in TURNOVER_SQL


def test_generation_is_idempotent_per_dedupe_key() -> None:
    existing = dedupe_key("org-a", "turnover", "wb", "default", "1", None)
    ch = FakeClickHouse().on("SELECT DISTINCT dedupe_key", [{"dedupe_key": existing}])
    created = insert_new_tasks(ch, "org-a", [_rec("1"), _rec("2"), _rec("2")], NOW)
    assert [c["product_id"] for c in created] == ["2"]
    ((_, params),) = ch.commands_matching("INSERT INTO dim_actionable_task")
    assert params["organization_id"] == "org-a"
    assert len(str(params["task_id"])) == 36
    assert params["dedupe_key"] == dedupe_key("org-a", "turnover", "wb", "default", "2", None)


def test_dedupe_keys_differ_between_orgs() -> None:
    assert dedupe_key("org-a", "t", "wb", "a", "1", None) != dedupe_key(
        "org-b", "t", "wb", "a", "1", None
    )


def test_digest_groups_by_org() -> None:
    message, total = build_digest(
        [("org-a", "turnover", "high", 2), ("org-b", "bad_ad", "medium", 1)],
        "https://stats.example.com/ui/#/dashboard",
    )
    assert total == 3
    assert "org-a" in message and "org-b" in message
    assert "https://stats.example.com" in message
    empty, zero = build_digest([], "")
    assert zero == 0 and "Нет открытых задач" in empty
