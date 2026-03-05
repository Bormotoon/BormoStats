from __future__ import annotations

from collectors.ozon.parsers import parse_finance_ops


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
