"""History store against real ClickHouse: migrated schema, SQL of writer, archive and reader."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.services.history_service import HistoryService
from app.tasks import maintenance
from app.utils.history_archive import archive_rows, backfill_done, backfill_table
from app.utils.history_store import HistoryStore, Observation
from app.utils.runtime import get_ch_client

ORG = "org-history-it"


def _register_account(client: Any, marketplace: str, account_id: str) -> None:
    client.command(
        "INSERT INTO dim_account (account_id, marketplace, title, organization_id)"
        " VALUES (%(a)s, %(m)s, 'history it', %(o)s)",
        parameters={"a": account_id, "m": marketplace, "o": ORG},
    )


def _card(price: int, title: str = "Mug") -> dict[str, Any]:
    return {
        "card": {
            "title": title,
            "photos": ["1.jpg"],
            "characteristics": [{"id": 1, "value": "red"}],
        },
        "price": {"price": price},
    }


def test_catalogue_history_round_trip(integration_runtime) -> None:
    client = integration_runtime.ch_client()
    try:
        _register_account(client, "wb", "hist-acc")
        t1, t2, t3 = (datetime(2026, 9, d, 10, tzinfo=UTC) for d in (1, 2, 3))

        def record(docs: dict[str, Any], at: datetime, run: str, **kwargs: Any) -> Any:
            return HistoryStore(client, run_id=run, source="it").record(
                marketplace="wb",
                account_id="hist-acc",
                repo="product",
                observations=[Observation(k, d, at) for k, d in docs.items()],
                **kwargs,
            )

        assert record({"1": _card(1000), "2": _card(50, "Cup")}, t1, "r1").created == 2
        assert record({"1": _card(1000), "2": _card(50, "Cup")}, t1, "r1b").commits == 0
        assert record({"1": _card(900), "2": _card(50, "Cup")}, t2, "r2").modified == 1
        gone = record({"1": _card(900)}, t3, "r3", tombstone_missing=True)
        assert gone.deleted == 1

        service = HistoryService(client, ORG)

        log = service.commits(
            repo="product",
            marketplace="wb",
            account_id="",
            entity_key="1",
            since=None,
            until=None,
            limit=10,
            offset=0,
        )
        assert [c["message"] for c in log] == ["changed 1 field(s)", "initial"]
        assert log[0]["parent_id"] == log[1]["commit_id"]
        assert log[0]["changed_paths"] == ["price.price"]

        changes = service.changes(
            repo="product",
            marketplace="wb",
            account_id="",
            entity_key="1",
            path_prefix="price",
            since=None,
            until=None,
            limit=10,
            offset=0,
        )
        assert [(c["path"], c["old_value"], c["new_value"]) for c in changes] == [
            ("price.price", 1000, 900)
        ]

        before = service.snapshot(
            repo="product", marketplace="wb", account_id="", entity_key="1", at=t1
        )
        after = service.snapshot(
            repo="product", marketplace="wb", account_id="", entity_key="1", at=t3
        )
        assert before is not None and before["document"]["price"]["price"] == 1000
        assert after is not None and after["document"]["price"]["price"] == 900
        cup = service.snapshot(
            repo="product", marketplace="wb", account_id="", entity_key="2", at=None
        )
        assert cup is not None and cup["is_deleted"] and cup["document"] is None

        shown = service.commit(log[0]["commit_id"])
        assert shown is not None and shown["changes"][0]["new_value"] == 900
        assert shown["document"]["card"]["characteristics"] == [{"id": 1, "value": "red"}]

        [repo] = service.repos()
        assert (repo["repo"], repo["entities"], repo["deleted_entities"], repo["commits"]) == (
            "product",
            2,
            1,
            4,
        )

        # another organization sees none of it
        stranger = HistoryService(client, "someone-else")
        assert stranger.repos() == []
        assert stranger.commit(log[0]["commit_id"]) is None
    finally:
        client.close()


def test_raw_rows_are_archived_backfilled_and_survive_prune(integration_runtime) -> None:
    client = get_ch_client()
    _register_account(client, "ozon", "hist-ozon")
    old = datetime(2025, 1, 10, 12, 0, 0)

    def posting(status: str) -> dict[str, Any]:
        return {
            "run_id": "00000000-0000-0000-0000-000000000001",
            "account_id": "hist-ozon",
            "posting_number": "P-1",
            "status": status,
            "created_at": old,
            "in_process_at": None,
            "shipped_at": None,
            "delivered_at": None,
            "canceled_at": None,
            "ozon_warehouse_id": None,
            "payload": json.dumps({"status": status}),
        }

    columns = list(posting("x"))
    # a row that existed before the archive did
    client.insert("raw_ozon_postings", [[posting("awaiting")[c] for c in columns]], columns)
    assert not backfill_done(client, "raw_ozon_postings")

    # pruning is held back until the table is imported
    report = maintenance.prune_old_raw(120)
    assert "raw_ozon_postings" in report["skipped_unarchived"]
    assert client.query("SELECT count() FROM raw_ozon_postings").result_rows[0][0] == 1

    assert backfill_table(client, "raw_ozon_postings", run_id="bf")["commits"] == 1
    assert backfill_done(client, "raw_ozon_postings")

    # the live ingest path sees the status change; the raw table would collapse it
    result = archive_rows(client, "raw_ozon_postings", [posting("delivered")], columns=columns)
    assert result is not None and result.modified == 1

    maintenance.prune_old_raw(120)
    settled = "SELECT count() FROM raw_ozon_postings"
    for _ in range(20):  # mutations run asynchronously
        if client.query(settled).result_rows[0][0] == 0:
            break
    log = HistoryService(client, ORG).commits(
        repo="raw_ozon_postings",
        marketplace="ozon",
        account_id="hist-ozon",
        entity_key="P-1",
        since=None,
        until=None,
        limit=10,
        offset=0,
    )
    assert [c["changed_paths"] for c in log] == [["payload.status", "status"], []]
    document = HistoryService(client, ORG).commit(log[1]["commit_id"])
    assert document is not None and document["document"]["payload"] == {"status": "awaiting"}
