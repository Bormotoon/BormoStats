from __future__ import annotations

from collectors.wb.parsers import parse_sales


def test_parse_sales_marks_return_rows() -> None:
    records = [
        {
            "srid": "sale-1",
            "lastChangeDate": "2026-03-01T12:00:00+03:00",
            "date": "2026-03-01T10:00:00+03:00",
            "nmId": 111,
            "chrtId": 222,
            "quantity": -1,
            "totalPrice": 100.0,
            "ppvzForPay": 85.0,
            "supplierOperName": "Возврат",
        }
    ]

    rows = parse_sales(records, run_id="run-1", account_id="acc-1")
    assert len(rows) == 1
    row = rows[0]
    assert row["srid"] == "sale-1"
    assert row["is_return"] == 1
    assert row["quantity"] == 1
    assert row["nm_id"] == 111
    assert row["chrt_id"] == 222
