"""Real ClickHouse regression: YM deduplication and raw -> stg -> marts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from collectors.ym.parsers import (
    parse_offer_mappings,
    parse_order_statistics,
    parse_orders,
    parse_prices,
    parse_stocks,
)

ROOT = Path(__file__).resolve().parents[2]


def seed_ym(ch: Any) -> None:
    now = datetime.now(UTC)
    run = str(uuid4())
    account = "777"
    ch.command(
        "INSERT INTO dim_account (account_id, marketplace, title, organization_id) VALUES"
        " ('777','ym','YM local check','default')"
    )
    order = {
        "orderId": 123,
        "campaignId": 777,
        "status": "DELIVERED",
        "creationDate": now.isoformat(),
        "items": [
            {
                "offerId": "YM-TEST",
                "count": 2,
                "prices": {"payment": {"value": 1800}, "subsidy": {"value": 200}},
            }
        ],
    }
    groups = {
        "raw_ym_orders": parse_orders([order], run, account),
        "raw_ym_order_stats": parse_order_statistics(
            [
                {
                    "id": 123,
                    "status": "DELIVERED",
                    "creationDate": now.isoformat(),
                    "items": [
                        {
                            "shopSku": "YM-TEST",
                            "count": 2,
                            "prices": [{"type": "BUYER", "costPerItem": 900}],
                        }
                    ],
                    "commissions": [
                        {"type": "FEE", "actual": 120},
                        {"type": "AGENCY", "actual": 20},
                    ],
                }
            ],
            run,
            account,
        ),
        "raw_ym_stocks": parse_stocks(
            [
                {
                    "warehouseId": 10,
                    "offers": [{"offerId": "YM-TEST", "stocks": [{"type": "FIT", "count": 8}]}],
                }
            ],
            run,
            account,
            now,
        ),
        "raw_ym_prices": parse_prices(
            [
                {
                    "offerId": "YM-TEST",
                    "price": {"value": 1000, "discountBase": 1200},
                    "buyerPrice": 900,
                }
            ],
            run,
            account,
            now,
        ),
        "raw_ym_offer_mappings": parse_offer_mappings(
            [
                {
                    "offer": {
                        "offerId": "YM-TEST",
                        "name": "Тестовый товар Маркета",
                        "pictures": [],
                    },
                    "mapping": {},
                }
            ],
            run,
            account,
        ),
    }
    for table, rows in groups.items():
        schema = {r[0] for r in ch.query(f"DESCRIBE TABLE {table}").result_rows}
        columns = [c for c in rows[0] if c in schema]
        data = [[r[c] for c in columns] for r in rows]
        ch.insert(table, data, column_names=columns)
        ch.insert(table, data, column_names=columns)
    ch.command(
        "INSERT INTO raw_ym_finance "
        "(run_id,account_id,transaction_id,event_date,offer_id,transaction_type,service_type,amount,ingested_at)"
        " VALUES ({r:UUID}, "
        "'777','sale',today(),'YM-TEST','sales','',2000,now()),({r:UUID},'777','return-delivery',today(),'YM-TEST','charge','reverse_logistics',-100,now())",
        parameters={"r": run},
    )


def test_ym_pipeline(integration_runtime: Any) -> None:
    ch = integration_runtime.ch_client()
    try:
        seed_ym(ch)
        assert (
            ch.query("SELECT count() FROM raw_ym_orders FINAL WHERE account_id='777'").first_row[0]
            == 1
        )
        for path in sorted((ROOT / "workers/app/sql/transforms").glob("ym_*_to_stg.sql")):
            ch.command(path.read_text(), parameters={"days": 30})
        ch.command((ROOT / "workers/app/sql/transforms/sync_dim_product_ym.sql").read_text())
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_finance_daily_ym.sql").read_text(),
            parameters={"days": 30},
        )
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_price_current.sql").read_text(),
            parameters={"built_at": datetime.now(UTC)},
        )
        assert ch.query(
            "SELECT qty, price_gross FROM stg_sales FINAL WHERE marketplace='ym' AND "
            "account_id='777'"
        ).first_row == (2, 1000.0)
        assert (
            ch.query(
                "SELECT amount FROM stg_stocks FINAL WHERE marketplace='ym' AND account_id='777'"
            ).first_row[0]
            == 8
        )
        assert ch.query(
            "SELECT seller_price, buyer_price, commission_pct, acquiring_rub "
            "FROM mrt_price_current FINAL WHERE "
            "marketplace='ym' AND account_id='777'"
        ).first_row == (1000.0, 900.0, 6.0, 10.0)
        quality = ch.query(
            "SELECT ym_costs_ready, ym_fee_source, margin_rub, breakeven_price "
            "FROM mrt_price_current FINAL WHERE marketplace='ym' AND account_id='777'"
        ).first_row
        assert quality == (0, "actual", None, None)
        assert ch.query(
            "SELECT sales, reverse_logistics, net_accrued FROM mrt_finance_daily FINAL WHERE "
            "marketplace='ym' AND account_id='777'"
        ).first_row == (2000.0, -100.0, 1900.0)
    finally:
        ch.close()


def test_tariff_forecast_used_only_for_matching_price(integration_runtime: Any) -> None:
    ch = integration_runtime.ch_client()
    try:
        seed_ym(ch)
        ch.command("TRUNCATE TABLE raw_ym_order_stats")
        ch.command(
            "INSERT INTO raw_ym_tariff_quotes "
            "(run_id,account_id,offer_id,price,fee,acquiring,logistics,payload,snapshot_ts) "
            "VALUES (generateUUIDv4(),'777','YM-TEST',1000,80,20,50,'{}',now())"
        )
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_price_current.sql").read_text(),
            parameters={"built_at": datetime.now(UTC)},
        )
        row = ch.query(
            "SELECT commission_pct, acquiring_rub, logistics_rub, ym_costs_ready, ym_fee_source "
            "FROM mrt_price_current FINAL "
            "WHERE marketplace='ym' AND account_id='777'"
        ).first_row
        assert row == (8.0, 20.0, 50.0, 1, "forecast")
        ch.command("TRUNCATE TABLE mrt_price_current")
        ch.command("TRUNCATE TABLE raw_ym_tariff_quotes")
        ch.command(
            "INSERT INTO raw_ym_tariff_quotes "
            "(run_id,account_id,offer_id,price,fee,acquiring,logistics,payload,snapshot_ts) "
            "VALUES (generateUUIDv4(),'777','YM-TEST',900,80,20,50,'{}',now())"
        )
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_price_current.sql").read_text(),
            parameters={"built_at": datetime.now(UTC)},
        )
        rejected = ch.query(
            "SELECT ym_costs_ready, ym_fee_source FROM mrt_price_current FINAL "
            "WHERE marketplace='ym' AND account_id='777'"
        ).first_row
        assert rejected == (0, "unknown")
    finally:
        ch.close()


def test_partial_return_preserves_delivery_and_counts_only_returned_units(
    integration_runtime: Any,
) -> None:
    import json

    ch = integration_runtime.ch_client()
    try:
        seed_ym(ch)
        ch.command("INSERT INTO raw_ym_delivered_snapshots SELECT * FROM raw_ym_orders FINAL")
        ch.command(
            "ALTER TABLE raw_ym_orders UPDATE status='PARTIALLY_RETURNED' WHERE account_id='777'",
            settings={"mutations_sync": 2},
        )
        payload = json.dumps(
            {
                "item": {
                    "details": [
                        {
                            "itemStatus": "RETURNED",
                            "itemCount": 1,
                            "updateDate": datetime.now(UTC).date().isoformat(),
                        },
                        {"itemStatus": "REJECTED", "itemCount": 1},
                    ]
                }
            }
        )
        ch.command(
            "ALTER TABLE raw_ym_order_stats UPDATE status='PARTIALLY_RETURNED', "
            "payload={payload:String} WHERE account_id='777'",
            parameters={"payload": payload},
            settings={"mutations_sync": 2},
        )
        ch.command(
            (ROOT / "workers/app/sql/transforms/ym_sales_to_stg.sql").read_text(),
            parameters={"days": 30},
        )
        rows = ch.query(
            "SELECT qty, payout, is_return FROM stg_sales FINAL "
            "WHERE marketplace='ym' AND account_id='777' ORDER BY is_return"
        ).result_rows
        assert rows == [(2, 2000.0, 0), (-1, -1000.0, 1)]
    finally:
        ch.close()
