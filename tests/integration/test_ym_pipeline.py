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


def test_ym_pnl_and_payout_reconciliation_without_double_ad_deduction(
    integration_runtime: Any,
) -> None:
    ch = integration_runtime.ch_client()
    try:
        seed_ym(ch)
        run = str(uuid4())
        # Add a boost charge in raw_ym_finance (-150), a payout (-1000), and a boost ad row (150)
        ch.command(
            "INSERT INTO raw_ym_finance "
            "(run_id,account_id,transaction_id,event_date,offer_id,transaction_type,service_type,amount,payout,ingested_at)"
            " VALUES "
            "({r:UUID},'777','boost-1',today(),'YM-TEST','charge','буст продаж',-150,0,now()),"
            "({r:UUID},'777','payout-1',today(),'','выплата продавцу',"
            "'перечисление продавцу',-1000,1000,now())",
            parameters={"r": run},
        )
        ch.command(
            "INSERT INTO raw_ym_ads "
            "(run_id,account_id,day,campaign_id,offer_id,product_id,impressions,clicks,cost,orders,revenue,ingested_at)"
            " VALUES ({r:UUID},'777',today(),'boost-camp','YM-TEST',1,1000,50,150,2,2000,now())",
            parameters={"r": run},
        )
        ch.command(
            "INSERT INTO dim_offer_cost (organization_id, offer_id, cost_price_rub, updated_at)"
            " VALUES ('default', 'YM-TEST', 300, now())"
        )
        for path in sorted((ROOT / "workers/app/sql/transforms").glob("ym_*_to_stg.sql")):
            ch.command(path.read_text(), parameters={"days": 30})
        ch.command((ROOT / "workers/app/sql/transforms/sync_dim_product_ym.sql").read_text())
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_ads_daily.sql").read_text(),
            parameters={"days": 30},
        )
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_finance_daily_ym.sql").read_text(),
            parameters={"days": 30},
        )
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_pnl_monthly.sql").read_text(),
            parameters={"days": 30},
        )
        fin = ch.query(
            "SELECT sales, reverse_logistics, other, net_accrued, payouts "
            "FROM mrt_finance_daily FINAL WHERE marketplace='ym' AND account_id='777'"
        ).first_row
        # Payout (-1000) is NOT in net_accrued; boost (-150) IS in other -> net_accrued = 1750
        assert fin == (2000.0, -100.0, -150.0, 1750.0, -1000.0)

        pnl = ch.query(
            "SELECT revenue_rub, other_costs_rub, net_accrued_rub, cogs_rub, gross_profit_rub, "
            "ad_cost_rub, operating_profit_rub "
            "FROM mrt_pnl_monthly FINAL WHERE marketplace='ym' AND account_id='777'"
        ).first_row
        # Boost (150) is already deducted in other_costs_rub/net_accrued_rub, so ad_cost_rub is 0
        # and operating_profit_rub does not subtract 150 a second time (1750 - 2*300 = 1150).
        assert pnl == (2000.0, 150.0, 1750.0, 600.0, 1150.0, 0.0, 1150.0)
    finally:
        ch.close()


def test_ym_catalog_sync_includes_cards_without_market_sku(integration_runtime: Any) -> None:
    import json

    ch = integration_runtime.ch_client()
    try:
        body = json.dumps(
            {
                "offer": {
                    "offerId": "NO-MSKU-1",
                    "name": "Товар без marketSku",
                    "vendor": "BrandY",
                    "pictures": ["https://avatars.mds.yandex.net/get-mpic/1/img"],
                },
                "market": {"marketCategoryName": "Категория ЯМ"},
            },
            ensure_ascii=False,
        )
        obj_hash = "a" * 64
        ch.command(
            "INSERT INTO hist_objects (object_hash, kind, size, body) "
            "VALUES ({h:String}, 'product', {sz:UInt32}, {b:String})",
            parameters={"h": obj_hash, "sz": len(body.encode()), "b": body},
        )
        ch.command(
            "INSERT INTO hist_refs "
            "(marketplace, account_id, repo, entity_key, head_commit, head_object, "
            "is_deleted, commit_count, first_seen_at, updated_at) "
            "VALUES ('ym', '777', 'product', 'NO-MSKU-1', "
            "{c:String}, {h:String}, 0, 1, now(), now())",
            parameters={"c": "b" * 64, "h": obj_hash},
        )
        ch.command((ROOT / "workers/app/sql/transforms/sync_dim_product_catalog.sql").read_text())
        row = ch.query(
            "SELECT offer_id, title, brand, category, image_url FROM dim_product FINAL "
            "WHERE marketplace='ym' AND account_id='777' AND offer_id='NO-MSKU-1'"
        ).first_row
        assert row == (
            "NO-MSKU-1",
            "Товар без marketSku",
            "BrandY",
            "Категория ЯМ",
            "https://avatars.mds.yandex.net/get-mpic/1/img",
        )
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


def test_market_sku_assignment_upgrades_product_id_without_duplicate_cards_or_split_history(
    integration_runtime: Any,
) -> None:
    ch = integration_runtime.ch_client()
    try:
        seed_ym(ch)
        for path in sorted((ROOT / "workers/app/sql/transforms").glob("ym_*_to_stg.sql")):
            ch.command(path.read_text(), parameters={"days": 30})
        ch.command((ROOT / "workers/app/sql/transforms/sync_dim_product_ym.sql").read_text())

        # Initially YM-TEST has market_sku = 0, so its product_id is cityHash64('YM-TEST').
        initial_cards = ch.query(
            "SELECT product_id, offer_id FROM dim_product FINAL "
            "WHERE marketplace='ym' AND account_id='777' AND offer_id='YM-TEST'"
        ).result_rows
        assert len(initial_cards) == 1
        fallback_pid = initial_cards[0][0]
        assert fallback_pid != "987654321"

        # Now Yandex assigns market_sku = 987654321 to YM-TEST.
        ch.command(
            "INSERT INTO raw_ym_offer_mappings "
            "(run_id, account_id, offer_id, market_sku, name, pictures, "
            "purchase_price, payload, ingested_at) "
            "VALUES (generateUUIDv4(), '777', 'YM-TEST', 987654321, 'Тестовый товар Маркета', "
            "[], 300, '{}', now() + INTERVAL 5 SECOND)"
        )
        ch.command("TRUNCATE TABLE stg_sales")
        ch.command("TRUNCATE TABLE stg_orders")
        ch.command("TRUNCATE TABLE stg_stocks")
        for path in sorted((ROOT / "workers/app/sql/transforms").glob("ym_*_to_stg.sql")):
            ch.command(path.read_text(), parameters={"days": 30})
        ch.command((ROOT / "workers/app/sql/transforms/sync_dim_product_ym.sql").read_text())
        ch.command(
            """
            ALTER TABLE dim_product DELETE
            WHERE marketplace = 'ym'
              AND offer_id != ''
              AND product_id = toString(cityHash64(offer_id))
              AND (account_id, offer_id) IN (
                SELECT account_id, offer_id
                FROM dim_product FINAL
                WHERE marketplace = 'ym'
                  AND offer_id != ''
                  AND product_id != toString(cityHash64(offer_id))
              )
            """,
            settings={"mutations_sync": 2},
        )
        ch.command(
            (ROOT / "workers/app/sql/marts/mrt_price_current.sql").read_text(),
            parameters={"built_at": datetime.now(UTC)},
        )

        # Only the canonical market_sku card remains in dim_product (no duplicate card).
        upgraded_cards = ch.query(
            "SELECT product_id, offer_id FROM dim_product FINAL "
            "WHERE marketplace='ym' AND account_id='777' AND offer_id='YM-TEST'"
        ).result_rows
        assert upgraded_cards == [("987654321", "YM-TEST")]

        # Historical sales, orders, stocks and current prices all resolve to 987654321.
        assert (
            ch.query(
                "SELECT product_id FROM stg_sales FINAL WHERE marketplace='ym' AND account_id='777'"
            ).first_row[0]
            == "987654321"
        )
        assert (
            ch.query(
                "SELECT product_id FROM stg_stocks FINAL "
                "WHERE marketplace='ym' AND account_id='777'"
            ).first_row[0]
            == "987654321"
        )
        assert ch.query(
            "SELECT product_id, title FROM mrt_price_current FINAL "
            "WHERE marketplace='ym' AND account_id='777'"
        ).first_row == ("987654321", "Тестовый товар Маркета")
    finally:
        ch.close()


def test_first_import_returned_order_recovers_sale_from_finance_or_marks_unobserved(
    integration_runtime: Any,
) -> None:
    import json

    ch = integration_runtime.ch_client()
    try:
        now = datetime.now(UTC)
        run = str(uuid4())
        return_payload = json.dumps(
            {
                "item": {
                    "details": [
                        {
                            "itemStatus": "RETURNED",
                            "itemCount": 1,
                            "updateDate": now.date().isoformat(),
                        }
                    ]
                }
            }
        )
        # Order 801: imported first time in RETURNED state, with confirmed payment in raw_ym_finance
        # Order 802: imported first time in RETURNED state, without any delivery snapshot or finance
        ch.command(
            "INSERT INTO raw_ym_orders "
            "(run_id, account_id, order_id, offer_id, product_id, status, substatus, "
            "created_at, updated_at, qty, buyer_price, seller_price, subsidy, payload, ingested_at)"
            " VALUES "
            "({r:UUID}, '777', 801, 'YM-801', 8010, 'RETURNED', '', "
            "now() - INTERVAL 2 DAY, now(), 1, 900, 1000, 100, '{}', now()),"
            "({r:UUID}, '777', 802, 'YM-802', 8020, 'RETURNED', '', "
            "now() - INTERVAL 2 DAY, now(), 1, 900, 1000, 100, '{}', now())",
            parameters={"r": run},
        )
        ch.command(
            "INSERT INTO raw_ym_order_stats "
            "(run_id, account_id, order_id, offer_id, product_id, status, created_at, updated_at, "
            "qty, buyer_price, payload, ingested_at) VALUES "
            "({r:UUID}, '777', 801, 'YM-801', 8010, 'RETURNED', "
            "now() - INTERVAL 2 DAY, now(), 1, 900, {p:String}, now()),"
            "({r:UUID}, '777', 802, 'YM-802', 8020, 'RETURNED', "
            "now() - INTERVAL 2 DAY, now(), 1, 900, {p:String}, now())",
            parameters={"r": run, "p": return_payload},
        )
        ch.command(
            "INSERT INTO raw_ym_finance "
            "(run_id, account_id, transaction_id, event_date, order_id, offer_id, "
            "transaction_type, service_type, amount, payout, payload, ingested_at) VALUES "
            "({r:UUID}, '777', 'fin-801', today() - 1, 801, 'YM-801', "
            "'Платеж покупателя', 'Платеж покупателя', 1000, 0, '{}', now())",
            parameters={"r": run},
        )
        ch.command(
            (ROOT / "workers/app/sql/transforms/ym_sales_to_stg.sql").read_text(),
            parameters={"days": 30},
        )
        rows = ch.query(
            "SELECT order_id, is_return, qty, payout, meta_json FROM stg_sales FINAL "
            "WHERE marketplace='ym' AND account_id='777' AND order_id IN ('801', '802') "
            "ORDER BY order_id, is_return"
        ).result_rows
        assert len(rows) == 3
        # Order 801 has both the finance-recovered sale (+1) and the return (-1)
        assert rows[0][:4] == ("801", 0, 1, 1000.0)
        assert "recovered_from_finance" in rows[0][4]
        assert rows[1][:4] == ("801", 1, -1, -1000.0)
        # Order 802 has no fake sale invented, and its return is marked unobserved
        assert rows[2][:4] == ("802", 1, -1, -1000.0)
        assert "return_without_observed_delivery" in rows[2][4]
    finally:
        ch.close()


def test_ym_pipeline_rebuild_is_idempotent(integration_runtime: Any) -> None:
    ch = integration_runtime.ch_client()
    try:
        seed_ym(ch)

        def run_all() -> tuple[Any, Any, Any]:
            for path in sorted((ROOT / "workers/app/sql/transforms").glob("ym_*_to_stg.sql")):
                ch.command(path.read_text(), parameters={"days": 30})
            ch.command((ROOT / "workers/app/sql/transforms/sync_dim_product_ym.sql").read_text())
            ch.command(
                (ROOT / "workers/app/sql/marts/mrt_sales_daily.sql").read_text(),
                parameters={"days": 30},
            )
            ch.command(
                (ROOT / "workers/app/sql/marts/mrt_finance_daily_ym.sql").read_text(),
                parameters={"days": 30},
            )
            sales = ch.query(
                "SELECT qty, revenue, payout, returns_qty FROM mrt_sales_daily FINAL "
                "WHERE marketplace='ym' AND account_id='777'"
            ).result_rows
            fin = ch.query(
                "SELECT sales, reverse_logistics, net_accrued FROM mrt_finance_daily FINAL "
                "WHERE marketplace='ym' AND account_id='777'"
            ).result_rows
            orders = ch.query(
                "SELECT count(), sum(qty) FROM stg_orders FINAL "
                "WHERE marketplace='ym' AND account_id='777'"
            ).first_row
            return sales, fin, orders

        first = run_all()
        second = run_all()
        assert first == second
    finally:
        ch.close()
