"""History store: commits only on change, tombstones, carried sections, raw archive, prune guard."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from app.tasks import maintenance
from app.utils import history_archive
from app.utils.history_archive import archive_rows, backfill_table
from app.utils.history_store import HistoryStore, Observation


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.result_rows = rows
        self._named: list[dict[str, Any]] = []

    def named_results(self) -> list[dict[str, Any]]:
        return self._named


class MemoryClickHouse:
    """Just enough of ClickHouse to run HistoryStore: rows live in dicts keyed like the tables."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.inserts: list[str] = []
        self.commands: list[str] = []
        self.done_sources: set[str] = set()
        self.raw_days: dict[str, dict[date, list[dict[str, Any]]]] = {}

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.tables.get(table, [])

    def _refs(self) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in self.rows("hist_refs"):
            key = (row["marketplace"], row["account_id"], row["repo"], row["entity_key"])
            latest[key] = row
        return latest

    def insert(self, table: str, data: list[list[Any]], column_names: list[str], **_: Any) -> None:
        self.inserts.append(table)
        self.tables.setdefault(table, []).extend(
            dict(zip(column_names, row, strict=True)) for row in data
        )

    def command(self, sql: str, parameters: dict[str, Any] | None = None, **_: Any) -> None:
        self.commands.append(sql)

    def query(self, sql: str, parameters: dict[str, Any] | None = None, **_: Any) -> _Result:
        params = parameters or {}
        if "FROM hist_refs FINAL" in sql:
            refs = [
                row
                for (mp, acc, repo, _key), row in self._refs().items()
                if (mp, acc, repo) == (params["marketplace"], params["account_id"], params["repo"])
            ]
            if "entity_key IN" in sql:
                refs = [row for row in refs if row["entity_key"] in params["keys"]]
                return _Result(
                    [
                        (
                            r["entity_key"],
                            r["head_commit"],
                            r["head_object"],
                            r["is_deleted"],
                            r["commit_count"],
                            r["first_seen_at"],
                        )
                        for r in refs
                    ]
                )
            return _Result([(r["entity_key"],) for r in refs if not r["is_deleted"]])
        if "SELECT object_hash, body FROM hist_objects" in sql:
            wanted = set(params["hashes"])
            return _Result(
                [
                    (o["object_hash"], o["body"])
                    for o in self.rows("hist_objects")
                    if o["object_hash"] in wanted
                ]
            )
        if "SELECT object_hash FROM hist_objects" in sql:
            wanted = set(params["hashes"])
            return _Result(
                [
                    (o["object_hash"],)
                    for o in self.rows("hist_objects")
                    if o["object_hash"] in wanted
                ]
            )
        if "FROM sys_watermarks" in sql:
            return _Result([(1 if params["source"] in self.done_sources else 0,)])
        if sql.startswith("SELECT min(toDate("):
            table = sql.split(" FROM ")[1].strip()
            days = sorted(self.raw_days.get(table, {}))
            return _Result([(days[0], days[-1])] if days else [(None, None)])
        if sql.startswith("SELECT * FROM"):
            table = sql.split()[3]
            result = _Result([])
            result._named = list(self.raw_days.get(table, {}).get(params["day"], []))
            return result
        raise AssertionError(f"unexpected query: {sql}")


def _store(client: MemoryClickHouse, run_id: str = "run-1") -> HistoryStore:
    return HistoryStore(client, run_id=run_id, source="test")


def _record(store: HistoryStore, docs: dict[str, Any], **kwargs: Any) -> Any:
    return store.record(
        marketplace="wb",
        account_id="acc",
        repo="product",
        observations=[Observation(key, doc) for key, doc in docs.items()],
        **kwargs,
    )


def _card(price: int = 1000, title: str = "Mug") -> dict[str, Any]:
    return {"card": {"title": title, "photos": ["a.jpg"]}, "price": {"price": price}}


def test_first_observation_creates_initial_commit_object_and_ref() -> None:
    ch = MemoryClickHouse()
    result = _record(_store(ch), {"1": _card()})

    assert (result.seen, result.created, result.commits) == (1, 1, 1)
    [commit] = ch.rows("hist_commits")
    assert commit["parent_id"] == "" and commit["message"] == "initial"
    [obj] = ch.rows("hist_objects")
    assert json.loads(obj["body"])["price"]["price"] == 1000
    [ref] = ch.rows("hist_refs")
    assert ref["head_commit"] == commit["commit_id"] and ref["commit_count"] == 1
    assert ch.rows("hist_changes") == []


def test_unchanged_catalogue_writes_nothing() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {"1": _card()})
    ch.inserts.clear()

    result = _record(_store(ch, "run-2"), {"1": _card()})

    assert (result.unchanged, result.commits) == (1, 0)
    assert ch.inserts == []


def test_price_change_is_a_child_commit_with_field_changes() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {"1": _card(1000)})
    first = ch.rows("hist_commits")[0]

    result = _record(_store(ch, "run-2"), {"1": _card(900)})

    assert result.modified == 1
    second = ch.rows("hist_commits")[1]
    assert second["parent_id"] == first["commit_id"]
    assert second["changed_paths"] == ["price.price"]
    [change] = ch.rows("hist_changes")
    assert (change["path"], change["op"], change["old_value"], change["new_value"]) == (
        "price.price",
        "change",
        "1000",
        "900",
    )
    assert change["commit_id"] == second["commit_id"]
    ref = ch._refs()[("wb", "acc", "product", "1")]
    assert ref["head_commit"] == second["commit_id"] and ref["commit_count"] == 2
    assert ref["first_seen_at"] == first["committed_at"]


def test_identical_content_of_two_products_is_stored_once() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {"1": _card(), "2": _card()})

    assert len(ch.rows("hist_commits")) == 2
    assert len(ch.rows("hist_objects")) == 1


def test_repeated_key_in_one_batch_chains_commits() -> None:
    ch = MemoryClickHouse()
    store = _store(ch)
    result = store.record(
        marketplace="wb",
        account_id="acc",
        repo="product",
        observations=[
            Observation("1", _card(1000)),
            Observation("1", _card(900)),
            Observation("1", _card(900)),
        ],
    )

    assert (result.created, result.modified, result.unchanged) == (1, 1, 1)
    first, second = ch.rows("hist_commits")
    assert second["parent_id"] == first["commit_id"]


def test_missing_product_gets_a_tombstone_and_restore_commit() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {"1": _card(), "2": _card(title="Cup")})

    result = _record(_store(ch, "run-2"), {"1": _card()}, tombstone_missing=True)
    assert result.deleted == 1
    tomb = [c for c in ch.rows("hist_commits") if c["is_deleted"]]
    assert [c["entity_key"] for c in tomb] == ["2"]
    assert ch._refs()[("wb", "acc", "product", "2")]["is_deleted"] == 1
    # deleted products are not tombstoned again
    assert _record(_store(ch, "run-3"), {"1": _card()}, tombstone_missing=True).commits == 0

    restored = _record(_store(ch, "run-4"), {"1": _card(), "2": _card(title="Cup")})
    assert restored.restored == 1
    assert ch._refs()[("wb", "acc", "product", "2")]["is_deleted"] == 0
    assert ch._refs()[("wb", "acc", "product", "2")]["commit_count"] == 3


def test_tombstones_are_skipped_when_most_of_the_catalogue_vanishes() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {str(n): _card(title=f"t{n}") for n in range(20)})

    result = _record(_store(ch, "run-2"), {"0": _card(title="t0")}, tombstone_missing=True)

    assert result.guard_triggered and result.skipped_tombstones == 19 and result.deleted == 0
    assert not any(c["is_deleted"] for c in ch.rows("hist_commits"))


def test_carried_section_does_not_read_as_removal() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {"1": _card(1000)})

    result = _record(
        _store(ch, "run-2"),
        {"1": {"card": {"title": "Mug", "photos": ["a.jpg"]}}},
        carry=("price",),
    )

    assert result.commits == 0

    changed = _record(
        _store(ch, "run-3"),
        {"1": {"card": {"title": "Big Mug", "photos": ["a.jpg"]}}},
        carry=("price",),
    )
    assert changed.modified == 1
    assert ch.rows("hist_commits")[-1]["changed_paths"] == ["card.title"]


def test_ignored_paths_never_cause_commits() -> None:
    ch = MemoryClickHouse()
    noisy = lambda stamp: {"card": {"title": "Mug", "updatedAt": stamp}}  # noqa: E731
    _record(_store(ch), {"1": noisy("t1")}, ignore=["card.updatedAt"])

    assert _record(_store(ch, "r2"), {"1": noisy("t2")}, ignore=["card.updatedAt"]).commits == 0


# -- raw archive --


def _posting(status: str, run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "account_id": "acc",
        "posting_number": "P-1",
        "status": status,
        "created_at": datetime(2026, 9, 1, 10, 0, 0),
        "payload": json.dumps({"status": status, "products": [{"sku": 1}]}),
    }


def test_archive_keeps_every_revision_of_a_replaced_raw_row() -> None:
    ch = MemoryClickHouse()
    columns = ["run_id", "account_id", "posting_number", "status", "created_at", "payload"]

    archive_rows(
        ch, "raw_ozon_postings", [_posting("awaiting", "r1")], run_id="r1", columns=columns
    )
    again = archive_rows(
        ch, "raw_ozon_postings", [_posting("awaiting", "r2")], run_id="r2", columns=columns
    )
    archive_rows(
        ch, "raw_ozon_postings", [_posting("delivered", "r3")], run_id="r3", columns=columns
    )

    assert again is not None and again.unchanged == 1  # a new run_id alone is not a change
    commits = ch.rows("hist_commits")
    assert [c["repo"] for c in commits] == ["raw_ozon_postings"] * 2
    assert {c["entity_key"] for c in commits} == {"P-1"}
    assert commits[1]["changed_paths"] == ["payload.status", "status"]
    body = json.loads(ch.rows("hist_objects")[0]["body"])
    assert body["payload"] == {"status": "awaiting", "products": [{"sku": 1}]}
    assert "run_id" not in body


def test_archive_ignores_unknown_tables_and_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ch = MemoryClickHouse()
    assert archive_rows(ch, "raw_competitor_prices", [{"account_id": "a"}]) is None
    monkeypatch.setenv("HISTORY_ENABLED", "false")
    assert archive_rows(ch, "raw_ozon_postings", [_posting("x", "r")]) is None
    assert ch.inserts == []


def test_snapshot_tables_are_keyed_without_the_snapshot_time() -> None:
    ch = MemoryClickHouse()
    row = {
        "account_id": "acc",
        "snapshot_ts": datetime(2026, 9, 1, 10, 0, 0),
        "ozon_product_id": 7,
        "warehouse_id": 3,
        "present": 5,
        "reserved": 0,
    }
    archive_rows(ch, "raw_ozon_stocks", [row])
    later = archive_rows(
        ch, "raw_ozon_stocks", [{**row, "snapshot_ts": datetime(2026, 9, 1, 10, 30)}]
    )
    changed = archive_rows(
        ch, "raw_ozon_stocks", [{**row, "snapshot_ts": datetime(2026, 9, 1, 11), "present": 4}]
    )

    assert later is not None and later.unchanged == 1
    assert changed is not None and changed.modified == 1
    commits = ch.rows("hist_commits")
    assert [c["entity_key"] for c in commits] == ["7|3", "7|3"]
    assert commits[1]["committed_at"] == datetime(2026, 9, 1, 11, tzinfo=UTC)


@pytest.mark.parametrize("tz", ["UTC", "Europe/Warsaw"])
@pytest.mark.parametrize("aware", [False, True])
def test_backfilled_rows_hash_like_the_rows_that_were_ingested(
    monkeypatch: pytest.MonkeyPatch, tz: str, aware: bool
) -> None:
    monkeypatch.setenv("TZ", tz)
    time.tzset()
    try:
        ch = MemoryClickHouse()
        columns = ["run_id", "account_id", "posting_number", "status", "created_at", "payload"]
        live = _posting("delivered", "r1")
        archive_rows(ch, "raw_ozon_postings", [live], columns=columns)
        # clickhouse_connect reads a naive datetime as process-local time and stores UTC,
        # so that is what a later SELECT returns for the very same row
        stored = live["created_at"].astimezone(UTC)
        from_db = {**live, "created_at": stored if aware else stored.replace(tzinfo=None)}
        ch.raw_days["raw_ozon_postings"] = {date(2026, 9, 1): [from_db]}

        assert backfill_table(ch, "raw_ozon_postings", run_id="bf")["commits"] == 0
    finally:
        monkeypatch.undo()
        time.tzset()


def test_backfill_imports_each_day_and_marks_table_done() -> None:
    ch = MemoryClickHouse()
    ch.raw_days["raw_ozon_postings"] = {
        date(2026, 9, 1): [{**_posting("delivered", "r1"), "ingested_at": datetime(2026, 9, 2)}],
        date(2026, 9, 3): [{**_posting("cancelled", "r2"), "posting_number": "P-2"}],
    }

    totals = backfill_table(ch, "raw_ozon_postings", run_id="bf")

    assert totals == {"rows": 2, "commits": 2}
    assert ch.rows("hist_commits")[0]["committed_at"] == datetime(2026, 9, 2, tzinfo=UTC)
    assert ch.rows("sys_watermarks")[0]["source"] == "history_backfill_done:raw_ozon_postings"


# -- retention --


def test_prune_leaves_tables_alone_until_they_are_archived(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = MemoryClickHouse()
    ch.done_sources = {history_archive.BACKFILL_MARKER_PREFIX + "raw_wb_sales"}
    monkeypatch.setattr(maintenance, "get_ch_client", lambda: ch)

    report = maintenance.prune_old_raw(120)

    assert [c.split()[2] for c in ch.commands] == ["raw_wb_sales"]
    assert report["tables"] == 1
    assert "raw_wb_orders" in report["skipped_unarchived"]


def test_prune_is_unchanged_when_history_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = MemoryClickHouse()
    monkeypatch.setenv("HISTORY_ENABLED", "false")
    monkeypatch.setattr(maintenance, "get_ch_client", lambda: ch)

    report = maintenance.prune_old_raw(120)

    assert len(ch.commands) == report["tables"] == 9


def test_retired_entities_get_one_deletion_commit_with_the_reason() -> None:
    ch = MemoryClickHouse()
    _record(_store(ch), {"old|1": _card(), "new|1": _card(title="Cup")})

    result = _record(
        _store(ch, "run-2"), {}, retire=["old|1", "never-seen"], retire_message="re-keyed"
    )
    assert result.deleted == 1
    tomb = [c for c in ch.rows("hist_commits") if c["is_deleted"]]
    assert [(c["entity_key"], c["message"]) for c in tomb] == [("old|1", "re-keyed")]
    assert ch._refs()[("wb", "acc", "product", "new|1")]["is_deleted"] == 0
    # retiring again changes nothing
    assert (
        _record(_store(ch, "run-3"), {}, retire=["old|1"], retire_message="re-keyed").commits == 0
    )


def test_balance_snapshots_are_archived_per_marketplace_and_only_on_change() -> None:
    ch = MemoryClickHouse()

    def snapshot(marketplace: str, hour: int, balance: float) -> dict[str, Any]:
        return {
            "run_id": "r",
            "marketplace": marketplace,
            "account_id": "acc",
            "snapshot_ts": datetime(2026, 9, 30, hour, tzinfo=UTC),
            "balance": balance,
            "for_withdraw": 0.0,
            "payload": "{}",
        }

    archive_rows(ch, "raw_marketplace_balance", [snapshot("wb", 10, 12180.09)])
    archive_rows(ch, "raw_marketplace_balance", [snapshot("ozon", 10, 47590.23)])
    unchanged = archive_rows(ch, "raw_marketplace_balance", [snapshot("wb", 11, 12180.09)])
    changed = archive_rows(ch, "raw_marketplace_balance", [snapshot("wb", 12, 12044.39)])

    assert unchanged is not None and unchanged.unchanged == 1
    assert changed is not None and changed.modified == 1
    commits = ch.rows("hist_commits")
    assert [(c["marketplace"], c["entity_key"]) for c in commits] == [
        ("wb", "wb"),
        ("ozon", "ozon"),
        ("wb", "wb"),
    ]
    assert commits[2]["committed_at"] == datetime(2026, 9, 30, 12, tzinfo=UTC)


def test_reordered_id_matched_list_is_not_a_commit() -> None:
    ch = MemoryClickHouse()
    attrs = [{"id": 1, "values": ["a.mp4"]}, {"id": 2, "values": ["gold"]}]
    _record(_store(ch), {"1": {"attributes": attrs}})

    result = _record(_store(ch, "run-2"), {"1": {"attributes": list(reversed(attrs))}})

    assert result.commits == 0 and result.unchanged == 1
    assert len(ch.rows("hist_commits")) == 1
