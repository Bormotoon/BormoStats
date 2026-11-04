"""Per-article unit economics, independently reconcilable to financial accruals."""

from __future__ import annotations

import calendar
import contextlib
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.daily_pnl_service import DailyPnlService, allocate
from clickhouse_connect.driver import Client

from common.article_economics import (
    EXPENSES,
    ZERO,
    AccrualEconomics,
    metric_row,
    number,
)
from common.ozon_buyouts import parse_buyouts
from common.pnl_tax import is_tax_applicable

_REF_IMG_PATH = Path(__file__).resolve().parents[3] / "common" / "economics_reference_images.json"
REFERENCE_IMAGES: dict[str, str] = (
    json.loads(_REF_IMG_PATH.read_text(encoding="utf-8")) if _REF_IMG_PATH.is_file() else {}
)


class ArticleEconomicsService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self.ch = ch
        self.org = organization_id

    def build(
        self,
        date_from: date,
        date_to: date,
        account_id: str | None = None,
        marketplace: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "oid": self.org,
            "start": date_from,
            "stop": date_to,
            "mp": marketplace or "",
            "aid": account_id or "",
        }
        accounts_query = (
            "SELECT marketplace, account_id FROM dim_account FINAL"
            " WHERE organization_id = {oid:String}"
            " AND ({mp:String} = '' OR marketplace = {mp:String})"
            " AND ({aid:String} = '' OR account_id = {aid:String})"
            " ORDER BY marketplace, account_id"
        )
        accounts_rows = list(self.ch.query(accounts_query, parameters=params).result_rows)
        accounts: list[tuple[str, str]] = [(str(r[0]), str(r[1])) for r in accounts_rows]
        if not accounts:
            return {
                "items": [],
                "total": None,
                "notes": ["Нет доступных кабинетов."],
            }
        marketplaces = sorted({mp for mp, _ in accounts})
        account_ids = sorted({aid for _, aid in accounts})
        params["accounts"] = accounts
        params["account_ids"] = account_ids
        params["marketplaces"] = marketplaces

        # 1. Product cards keyed by composite (marketplace, account_id, product_id)
        catalogue: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            catalogue = list(
                self.ch.query(
                    "SELECT marketplace, account_id, product_id, offer_id, title, image_url"
                    " FROM dim_product FINAL"
                    " WHERE (marketplace, account_id) IN {accounts:Array(Tuple(String, String))}",
                    parameters=params,
                ).named_results()
            )
        cards: dict[tuple[str, str, str], dict[str, Any]] = {
            (r["marketplace"], r["account_id"], str(r["product_id"])): r for r in catalogue
        }
        sku_cards_fallback: dict[tuple[str, str], dict[str, Any]] = {
            (r["marketplace"], str(r["product_id"])): r for r in catalogue
        }
        all_cards_fallback: dict[str, dict[str, Any]] = {str(r["product_id"]): r for r in catalogue}

        # 2. Costs: offer-level and product-level
        offer_costs: dict[tuple[str, str, str], Decimal] = {}
        with contextlib.suppress(Exception):
            for r in self.ch.query(
                "SELECT marketplace, account_id, offer_id, cost_price_rub FROM v_offer_cost"
                " WHERE (marketplace, account_id) IN {accounts:Array(Tuple(String, String))}",
                parameters=params,
            ).result_rows:
                if r[3] is not None:
                    offer_costs[(str(r[0]), str(r[1]), str(r[2]))] = number(r[3])

        dim_offer_costs: dict[str, Decimal] = {}
        with contextlib.suppress(Exception):
            for r in self.ch.query(
                "SELECT offer_id, cost_price_rub FROM dim_offer_cost FINAL"
                " WHERE organization_id = {oid:String}",
                parameters=params,
            ).result_rows:
                if r[1] is not None:
                    dim_offer_costs[str(r[0])] = number(r[1])

        sku_costs: dict[tuple[str, str], Decimal] = {}
        with contextlib.suppress(Exception):
            for r in self.ch.query(
                "SELECT marketplace, toString(product_id), cost_price_rub"
                " FROM dim_product_cost FINAL"
                " WHERE marketplace IN {marketplaces:Array(String)}",
                parameters=params,
            ).result_rows:
                if r[2] is not None:
                    sku_costs[(str(r[0]), str(r[1]))] = number(r[2])

        def resolve_cost(mp: str, acc: str, offer: str, sku: str) -> Decimal | None:
            if (mp, acc, offer) in offer_costs:
                return offer_costs[(mp, acc, offer)]
            if offer in dim_offer_costs:
                return dim_offer_costs[offer]
            if (mp, sku) in sku_costs:
                return sku_costs[(mp, sku)]
            return None

        # 3. Engines per marketplace
        engines: dict[str, AccrualEconomics] = {mp: AccrualEconomics() for mp in marketplaces}
        allocated_by_mp: dict[str, dict[str, Decimal]] = {}
        linked_ads_by_mp: dict[str, Decimal] = defaultdict(lambda: ZERO)
        matched_campaigns_by_mp: dict[str, int] = defaultdict(int)
        covered_cis: set[tuple[str, date]] = set()
        cis_missing_days: list[str] = []
        cis_complete = True

        # Ozon branch
        ozon_accounts = [aid for mp, aid in accounts if mp == "ozon"]
        if ozon_accounts:
            engine_ozon = engines["ozon"]
            ozon_params = {**params, "ozon_accounts": ozon_accounts}
            ops_sql = """SELECT payload FROM raw_ozon_finance_ops FINAL
              WHERE account_id IN {ozon_accounts:Array(String)} AND source='accrual_by_day'
              AND operation_ts >= toDateTime({start:Date}, 'Europe/Moscow')
              AND operation_ts < toDateTime(addDays({stop:Date},1), 'Europe/Moscow')"""
            with contextlib.suppress(Exception):
                stream = self.ch.query_row_block_stream(
                    ops_sql, parameters=ozon_params, settings={"max_block_size": 1024}
                )
                with stream:
                    for block in stream:
                        for (raw,) in block:
                            engine_ozon.add(json.loads(raw, parse_float=Decimal))

            # CIS Buyouts
            snapshots: list[tuple[Any, ...]] = []
            cis_sql = (
                "SELECT account_id, day, sku, offer_id, title, price, quantity, amount, payload "
                "FROM raw_ozon_cis_buyouts FINAL"
                " WHERE account_id IN {ozon_accounts:Array(String)}"
                " AND day >= {start:Date} AND day <= {stop:Date}"
            )
            with contextlib.suppress(Exception):
                snapshots = list(self.ch.query(cis_sql, parameters=ozon_params).result_rows)
            if not snapshots:
                cis_fallback_sql = (
                    "SELECT account_id, day, payload FROM raw_ozon_cis_buyouts FINAL"
                    " WHERE account_id IN {ozon_accounts:Array(String)}"
                    " AND day >= {start:Date} AND day <= {stop:Date}"
                )
                with contextlib.suppress(Exception):
                    snapshots = list(
                        self.ch.query(cis_fallback_sql, parameters=ozon_params).result_rows
                    )

            for row in snapshots:
                if len(row) >= 9:
                    (
                        account,
                        day,
                        sku_col,
                        offer_col,
                        title_col,
                        price_col,
                        qty_col,
                        amt_col,
                        raw,
                    ) = row[:9]
                    day_val = (
                        date.fromisoformat(str(day)[:10]) if not isinstance(day, date) else day
                    )
                    covered_cis.add((str(account), day_val))
                    if (sku_col or offer_col or qty_col or amt_col) and not (
                        raw and isinstance(raw, str) and raw.strip().startswith("{")
                    ):
                        qty = number(qty_col or 1)
                        price = number(price_col or 0)
                        amt = number(amt_col or 0)
                        p_line = {
                            "products": [
                                {
                                    "sku": str(sku_col).strip(),
                                    "posting_number": str(offer_col or sku_col).strip(),
                                    "offer_id": str(offer_col or "").strip(),
                                    "name": str(title_col or ""),
                                    "quantity": qty,
                                    "seller_price_per_instance": price,
                                    "amount": amt,
                                }
                            ]
                        }
                        engine_ozon.add_buyouts(day_val, p_line)
                        sku_cards_fallback.setdefault(
                            ("ozon", str(sku_col).strip()),
                            {"offer_id": str(offer_col or ""), "title": str(title_col or "")},
                        )
                        continue
                else:
                    account, day, raw = row[0], row[1], row[2]
                    day_val = (
                        date.fromisoformat(str(day)[:10]) if not isinstance(day, date) else day
                    )
                    covered_cis.add((str(account), day_val))

                payload = (
                    json.loads(raw, parse_float=Decimal) if isinstance(raw, str) else (raw or {})
                )
                if isinstance(payload, dict):
                    engine_ozon.add_buyouts(day_val, payload)
                    for record in parse_buyouts(payload):
                        sku_str = str(record["sku"])
                        sku_cards_fallback.setdefault(
                            ("ozon", sku_str),
                            {"offer_id": record["offer_id"], "title": record["title"]},
                        )

            requested_days = [
                date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)
            ]
            cis_missing_days = sorted(
                {
                    day.isoformat()
                    for account in ozon_accounts
                    for day in requested_days
                    if (account, day) not in covered_cis
                }
            )
            cis_complete = not cis_missing_days
            allocated_by_mp["ozon"] = engine_ozon.allocate()

            sku_ads: list[tuple[Any, ...]] = []
            ad_sql = (
                "SELECT day, campaign_id, toString(sku) AS sku, cost"
                " FROM raw_ozon_sku_ad_reports FINAL"
                " WHERE account_id IN {ozon_accounts:Array(String)}"
                " AND day >= {start:Date} AND day <= {stop:Date}"
            )
            with contextlib.suppress(Exception):
                sku_ads = list(self.ch.query(ad_sql, parameters=ozon_params).result_rows)
            linked_ads, matched_campaigns = engine_ozon.bind_ad_costs(sku_ads)
            if linked_ads:
                allocated_by_mp["ozon"]["marketing"] = (
                    allocated_by_mp["ozon"].get("marketing", ZERO) - linked_ads
                )
            linked_ads_by_mp["ozon"] = linked_ads
            matched_campaigns_by_mp["ozon"] = matched_campaigns

        # WB branch
        wb_accounts = [aid for mp, aid in accounts if mp == "wb"]
        if wb_accounts:
            engine_wb = engines["wb"]
            wb_params = {**params, "wb_accounts": wb_accounts}
            wb_report_days: set[date] = set()

            wb_sql = (
                "SELECT day, account_id, payload FROM raw_wb_finance_report FINAL"
                " WHERE account_id IN {wb_accounts:Array(String)}"
                " AND day BETWEEN {start:Date} AND {stop:Date}"
            )
            with contextlib.suppress(Exception):
                for r in self.ch.query(wb_sql, parameters=wb_params).named_results():
                    day_val = r["day"]
                    if isinstance(day_val, str):
                        day_val = date.fromisoformat(day_val[:10])
                    wb_report_days.add(day_val)
                    raw_p = r["payload"]
                    p = json.loads(raw_p, parse_float=Decimal) if isinstance(raw_p, str) else raw_p
                    if isinstance(p, dict):
                        engine_wb.add_wb_realization_row(p)

            # Check missing days for fallback from stg_sales + mrt_price_current
            all_days = [
                date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)
            ]
            missing_wb_days = [d for d in all_days if d not in wb_report_days]
            if missing_wb_days:
                wb_sales_sql = """SELECT
                  s.day AS day,
                  s.account_id AS account_id,
                  s.product_id AS product_id,
                  sum(s.qty) AS qty,
                  sum(s.sales_rub) AS sales_rub,
                  any(p.commission_pct) AS commission_pct,
                  any(p.acquiring_rub) AS acquiring_rub,
                  any(p.logistics_rub) AS logistics_rub
                FROM stg_sales AS s FINAL
                LEFT JOIN mrt_price_current AS p FINAL
                  ON s.marketplace = p.marketplace
                  AND s.account_id = p.account_id
                  AND s.product_id = p.product_id
                WHERE s.marketplace = 'wb'
                  AND s.account_id IN {wb_accounts:Array(String)}
                  AND s.day IN {missing_days:Array(Date)}
                GROUP BY s.day, s.account_id, s.product_id"""
                with contextlib.suppress(Exception):
                    for r in self.ch.query(
                        wb_sales_sql,
                        parameters={**wb_params, "missing_days": missing_wb_days},
                    ).named_results():
                        q = Decimal(str(r["qty"]))
                        rev = Decimal(str(r["sales_rub"]))
                        comm_p = Decimal(str(r.get("commission_pct") or 0))
                        comm = rev * comm_p / Decimal(100)
                        acq = Decimal(str(r.get("acquiring_rub") or 0)) * abs(q)
                        logist = Decimal(str(r.get("logistics_rub") or 0)) * abs(q)
                        engine_wb.add_standardized_sale(
                            sku=str(r["product_id"]),
                            qty=q,
                            revenue=rev,
                            buyer_revenue=rev,
                            commission=comm,
                            acquiring=acq,
                            logistics=logist,
                        )

            # Reconcile with mrt_finance_daily.net_accrued
            wb_fin_sql = (
                "SELECT sum(net_accrued) AS total_net_accrued "
                "FROM mrt_finance_daily FINAL "
                "WHERE marketplace = 'wb' AND account_id IN {wb_accounts:Array(String)} "
                "AND day BETWEEN {start:Date} AND {stop:Date}"
            )
            with contextlib.suppress(Exception):
                fin_res = list(self.ch.query(wb_fin_sql, parameters=wb_params).named_results())
                if fin_res and fin_res[0].get("total_net_accrued") is not None:
                    target_net = Decimal(str(fin_res[0]["total_net_accrued"]))
                    delta = target_net - engine_wb.raw_total
                    if abs(delta) > ZERO:
                        engine_wb.rows["unallocated"]["other_accruals"] -= delta
                        engine_wb.raw_total += delta

            allocated_by_mp["wb"] = engine_wb.allocate()

            # WB Ads linking
            wb_ads_linked = ZERO
            with contextlib.suppress(Exception):
                wb_perf_sql = (
                    "SELECT toString(product_id) AS sku, sum(cost) AS cost "
                    "FROM mrt_ad_performance_daily FINAL "
                    "WHERE marketplace = 'wb' AND account_id IN {wb_accounts:Array(String)} "
                    "AND day BETWEEN {start:Date} AND {stop:Date} "
                    "GROUP BY product_id"
                )
                for r in self.ch.query(wb_perf_sql, parameters=wb_params).named_results():
                    amt = number(r["cost"])
                    if amt:
                        engine_wb.rows[str(r["sku"])]["marketing"] += amt
                        wb_ads_linked += amt

                wb_total_ads_sql = (
                    "SELECT sum(cost) AS total_cost FROM mrt_ads_daily FINAL "
                    "WHERE marketplace = 'wb' AND account_id IN {wb_accounts:Array(String)} "
                    "AND day BETWEEN {start:Date} AND {stop:Date}"
                )
                tot_ads_res = list(
                    self.ch.query(wb_total_ads_sql, parameters=wb_params).named_results()
                )
                if tot_ads_res and tot_ads_res[0].get("total_cost") is not None:
                    tot_ads = number(tot_ads_res[0]["total_cost"])
                    unalloc_ads = max(ZERO, tot_ads - wb_ads_linked)
                    if unalloc_ads:
                        engine_wb.rows["unallocated"]["marketing"] += unalloc_ads

            linked_ads_by_mp["wb"] = wb_ads_linked

        # YM branch
        ym_accounts = [aid for mp, aid in accounts if mp == "ym"]
        if ym_accounts:
            engine_ym = engines["ym"]
            ym_params = {**params, "ym_accounts": ym_accounts}

            ym_sales_sql = """SELECT
              s.day AS day,
              s.account_id AS account_id,
              s.product_id AS product_id,
              sum(s.qty) AS qty,
              sum(s.sales_rub) AS sales_rub,
              any(p.commission_pct) AS commission_pct,
              any(p.acquiring_rub) AS acquiring_rub,
              any(p.logistics_rub) AS logistics_rub
            FROM stg_sales AS s FINAL
            LEFT JOIN mrt_price_current AS p FINAL
              ON s.marketplace = 'ym'
              AND s.account_id = p.account_id
              AND s.product_id = p.product_id
            WHERE s.marketplace = 'ym'
              AND s.account_id IN {ym_accounts:Array(String)}
              AND s.day BETWEEN {start:Date} AND {stop:Date}
            GROUP BY s.day, s.account_id, s.product_id"""
            with contextlib.suppress(Exception):
                for r in self.ch.query(ym_sales_sql, parameters=ym_params).named_results():
                    q = Decimal(str(r["qty"]))
                    rev = Decimal(str(r["sales_rub"]))
                    comm_p = Decimal(str(r.get("commission_pct") or 0))
                    comm = rev * comm_p / Decimal(100)
                    acq = Decimal(str(r.get("acquiring_rub") or 0)) * abs(q)
                    logist = Decimal(str(r.get("logistics_rub") or 0)) * abs(q)
                    engine_ym.add_standardized_sale(
                        sku=str(r["product_id"]),
                        qty=q,
                        revenue=rev,
                        buyer_revenue=rev,
                        commission=comm,
                        acquiring=acq,
                        logistics=logist,
                    )

            # Reconcile with mrt_finance_daily.net_accrued
            ym_fin_sql = (
                "SELECT sum(net_accrued) AS total_net_accrued "
                "FROM mrt_finance_daily FINAL "
                "WHERE marketplace = 'ym' AND account_id IN {ym_accounts:Array(String)} "
                "AND day BETWEEN {start:Date} AND {stop:Date}"
            )
            with contextlib.suppress(Exception):
                fin_res = list(self.ch.query(ym_fin_sql, parameters=ym_params).named_results())
                if fin_res and fin_res[0].get("total_net_accrued") is not None:
                    target_net = Decimal(str(fin_res[0]["total_net_accrued"]))
                    delta = target_net - engine_ym.raw_total
                    if abs(delta) > ZERO:
                        engine_ym.rows["unallocated"]["other_accruals"] -= delta
                        engine_ym.raw_total += delta

            allocated_by_mp["ym"] = engine_ym.allocate()

            # YM Ads linking
            ym_ads_linked = ZERO
            with contextlib.suppress(Exception):
                ym_perf_sql = (
                    "SELECT toString(product_id) AS sku, sum(cost) AS cost "
                    "FROM mrt_ad_performance_daily FINAL "
                    "WHERE marketplace = 'ym' AND account_id IN {ym_accounts:Array(String)} "
                    "AND day BETWEEN {start:Date} AND {stop:Date} "
                    "GROUP BY product_id"
                )
                for r in self.ch.query(ym_perf_sql, parameters=ym_params).named_results():
                    amt = number(r["cost"])
                    if amt:
                        engine_ym.rows[str(r["sku"])]["marketing"] += amt
                        ym_ads_linked += amt

                ym_total_ads_sql = (
                    "SELECT sum(cost) AS total_cost FROM mrt_ads_daily FINAL "
                    "WHERE marketplace = 'ym' AND account_id IN {ym_accounts:Array(String)} "
                    "AND day BETWEEN {start:Date} AND {stop:Date}"
                )
                tot_ads_res = list(
                    self.ch.query(ym_total_ads_sql, parameters=ym_params).named_results()
                )
                if tot_ads_res and tot_ads_res[0].get("total_cost") is not None:
                    tot_ads = number(tot_ads_res[0]["total_cost"])
                    unalloc_ads = max(ZERO, tot_ads - ym_ads_linked)
                    if unalloc_ads:
                        engine_ym.rows["unallocated"]["marketing"] += unalloc_ads

            linked_ads_by_mp["ym"] = ym_ads_linked

        # 6. Taxes: scoped per marketplace/account
        rate = number(os.getenv("PNL_TAX_RATE_PCT", "8"))
        taxes: dict[tuple[str, str], Decimal] = {}
        tax_estimate = False
        any_tax_enabled = False

        for mp, aid in accounts:
            if is_tax_applicable(self.org, mp, aid):
                any_tax_enabled = True
                with contextlib.suppress(Exception):
                    daily_res = DailyPnlService(self.ch, self.org).build(
                        date_from, date_to, mp, aid
                    )
                    target_tax = sum((number(r["tax"]) for r in daily_res["items"]), ZERO)
                    if any(r.get("tax_status") == "estimated" for r in daily_res["items"]):
                        tax_estimate = True
                    mp_engine = engines[mp]
                    sku_weights = {
                        sku: row["buyer_revenue"]
                        for sku, row in mp_engine.rows.items()
                        if row["buyer_revenue"] > ZERO and sku != "unallocated"
                    }
                    skus = list(sku_weights)
                    if not skus and target_tax > ZERO:
                        taxes[(mp, "unallocated")] = (
                            taxes.get((mp, "unallocated"), ZERO) + target_tax
                        )
                    elif skus:
                        allocated_taxes = allocate(target_tax, [sku_weights[s] for s in skus])
                        for s, t in zip(skus, allocated_taxes, strict=True):
                            taxes[(mp, s)] = taxes.get((mp, s), ZERO) + t

        # 7. Additional external expenses
        external = ZERO
        external_unknown = False
        expense_sql = (
            "SELECT month, expense_date, amount_rub FROM dim_additional_expense FINAL"
            " WHERE organization_id={oid:String}"
            " AND month >= toStartOfMonth({start:Date}) AND month <= toStartOfMonth({stop:Date})"
        )
        with contextlib.suppress(Exception):
            for month, expense_date, amount in self.ch.query(
                expense_sql, parameters=params
            ).result_rows:
                if expense_date is not None:
                    exp_d = (
                        date.fromisoformat(str(expense_date)[:10])
                        if not isinstance(expense_date, date)
                        else expense_date
                    )
                    if date_from <= exp_d <= date_to:
                        external += number(amount)
                    continue
                m_date = (
                    date.fromisoformat(str(month)[:10]) if not isinstance(month, date) else month
                )
                last = m_date.replace(day=calendar.monthrange(m_date.year, m_date.month)[1])
                if date_from <= m_date and date_to >= last:
                    external += number(amount)
                elif number(amount):
                    count = calendar.monthrange(m_date.year, m_date.month)[1]
                    portions = allocate(number(amount), [Decimal(1)] * count)
                    external += sum(
                        (
                            part
                            for i, part in enumerate(portions)
                            if date_from <= m_date + timedelta(days=i) <= date_to
                        ),
                        ZERO,
                    )

        # 8. Assemble result rows
        items: list[dict[str, Any]] = []
        missing: list[str] = []
        period = (
            date_from.strftime("%d.%m")
            if date_from == date_to
            else f"{date_from:%d.%m.%Y} - {date_to:%d.%m.%Y}"
        )

        for mp in marketplaces:
            mp_accounts = [aid for m, aid in accounts if m == mp]
            primary_acc = mp_accounts[0] if len(mp_accounts) == 1 else (account_id or "default")
            mp_engine = engines[mp]

            for sku, source in mp_engine.rows.items():
                r = {
                    key: source[key]
                    for key in (
                        *EXPENSES,
                        "sales_qty",
                        "returns_qty",
                        "revenue",
                        "buyer_revenue",
                        "commission",
                        "allocated_cost",
                        "sales_cis",
                        "revenue_rf",
                        "revenue_cis",
                        "buyer_rf",
                        "buyer_cis",
                        "commission_rf",
                        "commission_cis",
                    )
                }
                r["cis_qty"] = r["sales_cis"]
                card = (
                    cards.get((mp, primary_acc, sku))
                    or sku_cards_fallback.get((mp, sku))
                    or all_cards_fallback.get(sku, {})
                )
                if sku == "unallocated":
                    offer = (
                        "Расходы без привязки"
                        if len(marketplaces) == 1
                        else f"Расходы без привязки ({mp.upper()})"
                    )
                else:
                    offer = card.get("offer_id") or f"SKU {sku}"

                cost = resolve_cost(mp, primary_acc, offer, sku)
                units = r["sales_qty"] + r["returns_qty"] + r["cis_qty"]
                r["cogs"] = cost * units if cost is not None else (ZERO if not units else None)
                if r["cogs"] is None:
                    missing.append(offer)

                if sku == "unallocated":
                    r["external"] = external / Decimal(len(marketplaces)) if marketplaces else ZERO
                else:
                    r["external"] = ZERO

                r["tax"] = taxes.get((mp, sku), ZERO) if any_tax_enabled else ZERO
                r["tax_main"] = r["tax"]
                r = metric_row(r)
                r.update(
                    sku=sku,
                    offer_id=offer,
                    title=card.get("title") or "",
                    image_url=card.get("image_url") or REFERENCE_IMAGES.get(offer),
                    period=period,
                    marketplace=mp,
                    account_id=primary_acc,
                )
                if mp == "ozon" and not cis_complete:
                    for key in ("revenue_cis", "buyer_cis", "commission_cis", "sales_cis"):
                        r[key] = None
                r.update(self_purchases=None, vat=None)
                items.append(r)

        # 9. ABC classification
        for key, letter in [
            ("revenue", "revenue_abc"),
            ("operating", "operating_abc"),
            ("profit", "profit_abc"),
        ]:
            candidates = sorted(
                (r for r in items if r[key] is not None and r[key] > 0),
                key=lambda r: -r[key],
            )
            denom = sum(r[key] for r in candidates)
            running = ZERO
            for r in candidates:
                r[letter] = (
                    "A"
                    if running < denom * Decimal("0.8")
                    else "B"
                    if running < denom * Decimal("0.95")
                    else "C"
                )
                running += r[key]
            for r in items:
                r[letter] = r.get(letter, "—" if r[key] is None else "C")

        for r in items:
            r["abc"] = r["revenue_abc"] + r["operating_abc"] + r["profit_abc"]

        items.sort(key=lambda r: -r["revenue"])
        additive = (
            *EXPENSES,
            "sales_qty",
            "returns_qty",
            "revenue",
            "buyer_revenue",
            "commission",
            "net_accrued",
            "cogs",
            "external",
            "tax",
            "tax_main",
            "allocated_cost",
            "cis_qty",
            "sales_cis",
            "revenue_rf",
            "revenue_cis",
            "buyer_rf",
            "buyer_cis",
            "commission_rf",
            "commission_cis",
        )
        total = metric_row(
            {
                key: (
                    None
                    if any(r.get(key) is None for r in items)
                    else sum((r[key] for r in items), ZERO)
                )
                for key in additive
            }
        )
        total_mp = marketplaces[0] if len(marketplaces) == 1 else "mixed"
        total.update(
            offer_id="Итого",
            period="Итого",
            abc="—",
            sku="total",
            image_url=None,
            marketplace=total_mp,
        )

        def serial(row: dict[str, Any]) -> dict[str, Any]:
            return {
                k: float(v.quantize(Decimal(".000001"))) if isinstance(v, Decimal) else v
                for k, v in row.items()
            }

        total_operations = sum(e.operations for e in engines.values())
        total_raw_net = sum(e.raw_total for e in engines.values())
        total_linked_ads = sum(linked_ads_by_mp.values())
        combined_unattributed: dict[str, float] = {}
        for alloc in allocated_by_mp.values():
            for k, v in alloc.items():
                combined_unattributed[k] = combined_unattributed.get(k, 0.0) + float(v)

        return {
            "items": [serial(r) for r in items],
            "total": serial(total),
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "tax_rate_pct": float(rate),
            "tax_enabled": any_tax_enabled,
            "tax_estimate": any_tax_enabled and tax_estimate,
            "missing_costs": missing,
            "operations": total_operations,
            "source_net_accrued": float(total_raw_net),
            "source_finance_accruals": (
                float(engines["ozon"].raw_total) if "ozon" in engines else 0.0
            ),
            "cis_buyout_receipts": (
                float(engines["ozon"].buyout_receipts) if "ozon" in engines else 0.0
            ),
            "cis_coverage_complete": cis_complete,
            "cis_missing_days": cis_missing_days,
            "cis_days_loaded": len(covered_cis),
            "cis_overlap_prevented": (
                engines["ozon"].buyout_overlap_count if "ozon" in engines else 0
            ),
            "unattributed_costs": combined_unattributed,
            "ads_sku_linked": float(total_linked_ads),
            "ads_campaign_days_linked": sum(matched_campaigns_by_mp.values()),
            "external_period_incomplete": external_unknown,
            "notes": [
                "Расходы без подтверждённого SKU сохранены в строке «Расходы без привязки». "
                "Пропорционального распределения между артикулами нет.",
                "СНГ/ЕАЭС: отдельный отчёт /v1/finance/products/buyout; сумма продаж включена "
                "один раз по отправлению и SKU. Доставка уже учтена в основной ленте "
                "и повторно не начисляется.",
                "Комиссия/скидка СНГ = цена продавца * количество - фактическая сумма "
                "к начислению в отчёте выкупов. Общая ставка комиссии РФ вместо неё не "
                "подставляется.",
                "Нет загруженного отчёта СНГ за день — это отсутствие данных, не ноль. "
                "Самовыкупы и отдельный НДС пока не настроены.",
                "ABC: выручка / операционная прибыль / чистая прибыль; границы 80% и 95%.",
                "Реклама: фактический расход по SKU из Performance API. Сопоставление "
                "с начислениями по дню и кампании; остаток и разница сумм сохранены "
                "в строке «Расходы без привязки», повторно не вычитаются.",
                "Внешние расходы с датой учитываются в указанный день в строке без привязки. "
                "Старые месячные расходы учитываются целиком за полный месяц; за фрагмент "
                "месяца распределяются по календарным дням, как в P&L.",
                "Налог за полный закрытый месяц — по реализации; за отдельные дни "
                "используется календарное распределение месячного налога, как в P&L; "
                "открытые месяцы предварительные.",
            ],
        }
