from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from collectors.ozon.parsers import parse_finance_ops, parse_postings, parse_stocks

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_json_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_parse_finance_ops_maps_basic_fields() -> None:
    records = [
        {
            "operation_id": "op-1",
            "operation_date": "2026-03-01T10:15:00Z",
            "type": "sale",
            "amount": {"value": "123.45", "currency_code": "RUB"},
        }
    ]

    rows = parse_finance_ops(records, run_id="run-1", account_id="acc-1")
    assert len(rows) == 1
    row = rows[0]
    assert row["operation_id"] == "op-1"
    assert row["type"] == "sale"
    assert row["amount"] == 123.45
    assert row["currency"] == "RUB"


def test_parse_postings_maps_cancelled_at_from_cancellation_payload() -> None:
    cancelled_posting = _load_json_fixture("ozon_cancelled_posting.json")

    posting_rows, item_rows = parse_postings(
        [cancelled_posting],
        run_id="run-1",
        account_id="acc-1",
    )

    assert len(posting_rows) == 1
    assert len(item_rows) == 1
    assert posting_rows[0]["posting_number"] == "POST-1"
    assert posting_rows[0]["status"] == "cancelled"
    assert posting_rows[0]["canceled_at"] == datetime(2026, 3, 2, 11, 22, 33)


def test_parse_postings_supports_top_level_canceled_at_variant() -> None:
    cancelled_posting = _load_json_fixture("ozon_cancelled_posting.json")
    cancelled_posting["canceled_at"] = "2026-03-04T01:02:03Z"
    cancelled_posting.pop("cancellation", None)

    posting_rows, _ = parse_postings(
        [cancelled_posting],
        run_id="run-1",
        account_id="acc-1",
    )

    assert posting_rows[0]["canceled_at"] == datetime(2026, 3, 4, 1, 2, 3)


def test_parse_finance_ops_supports_flat_amount_and_alias_fields() -> None:
    records = [
        {
            "transaction_id": "txn-1",
            "created_at": "2026-03-01T10:15:00Z",
            "operation_type": "service_fee",
            "accruals_for_sale": "17.25",
            "currency": "RUB",
        }
    ]

    rows = parse_finance_ops(records, run_id="run-1", account_id="acc-1")

    assert len(rows) == 1
    row = rows[0]
    assert row["operation_id"] == "txn-1"
    assert row["type"] == "service_fee"
    assert row["amount"] == 17.25
    assert row["currency"] == "RUB"


def test_parse_stocks_supports_flat_variant_without_nested_stocks() -> None:
    rows = parse_stocks(
        [
            {
                "product_id": 100500,
                "offer_id": "offer-1",
                "warehouse_id": 12,
                "present": 9,
                "reserved": 2,
            }
        ],
        run_id="run-1",
        account_id="acc-1",
        snapshot_ts=datetime(2026, 3, 1, 12, 0, 0),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ozon_product_id"] == 100500
    assert row["warehouse_id"] == 12
    assert row["present"] == 9
    assert row["reserved"] == 2
