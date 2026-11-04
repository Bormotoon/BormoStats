"""Per-article unit economics, independently reconcilable to financial accruals."""

from __future__ import annotations

import calendar
import contextlib
import json
import os
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
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"oid": self.org, "start": date_from, "stop": date_to}
        accounts = [
            r[0]
            for r in self.ch.query(
                "SELECT account_id FROM dim_account FINAL"
                " WHERE organization_id={oid:String} AND marketplace='ozon'",
                parameters=params,
            ).result_rows
        ]
        if account_id:
            accounts = [a for a in accounts if a == account_id]
        if not accounts:
            return {
                "items": [],
                "total": None,
                "notes": ["Нет доступных кабинетов Ozon."],
            }
        params["accounts"] = accounts

        # 1. Product cards keyed by composite (account_id, product_id) (Copilot #8)
        catalogue = list(
            self.ch.query(
                "SELECT account_id, product_id, offer_id, title, image_url"
                " FROM dim_product FINAL"
                " WHERE marketplace='ozon' AND account_id IN {accounts:Array(String)}",
                parameters=params,
            ).named_results()
        )
        cards: dict[tuple[str, str], dict[str, Any]] = {
            (r["account_id"], str(r["product_id"])): r for r in catalogue
        }
        # Sku-only fallback for buyouts where account_id may not be present in catalogue
        sku_cards_fallback: dict[str, dict[str, Any]] = {str(r["product_id"]): r for r in catalogue}

        # 2. Costs: offer-level and product-level
        offer_costs: dict[tuple[str, str], Decimal] = {}
        with contextlib.suppress(Exception):
            for r in self.ch.query(
                "SELECT account_id, offer_id, cost_price_rub FROM v_offer_cost"
                " WHERE marketplace='ozon' AND account_id IN {accounts:Array(String)}",
                parameters=params,
            ).result_rows:
                if r[2] is not None:
                    offer_costs[(str(r[0]), str(r[1]))] = number(r[2])

        dim_offer_costs: dict[str, Decimal] = {}
        with contextlib.suppress(Exception):
            for r in self.ch.query(
                "SELECT offer_id, cost_price_rub FROM dim_offer_cost FINAL"
                " WHERE organization_id={oid:String}",
                parameters=params,
            ).result_rows:
                if r[1] is not None:
                    dim_offer_costs[str(r[0])] = number(r[1])

        sku_costs: dict[str, Decimal] = {}
        with contextlib.suppress(Exception):
            for r in self.ch.query(
                "SELECT product_id, cost_price_rub FROM dim_product_cost FINAL"
                " WHERE marketplace='ozon'"
            ).result_rows:
                if r[1] is not None:
                    sku_costs[str(r[0])] = number(r[1])

        def resolve_cost(acc: str, offer: str, sku: str) -> Decimal | None:
            if (acc, offer) in offer_costs:
                return offer_costs[(acc, offer)]
            if offer in dim_offer_costs:
                return dim_offer_costs[offer]
            return sku_costs.get(sku)

        # 3. Accrual processing
        engine = AccrualEconomics()
        ops_sql = """SELECT payload FROM raw_ozon_finance_ops FINAL
          WHERE account_id IN {accounts:Array(String)} AND source='accrual_by_day'
          AND operation_ts >= toDateTime({start:Date}, 'Europe/Moscow')
          AND operation_ts < toDateTime(addDays({stop:Date},1), 'Europe/Moscow')"""
        with self.ch.query_row_block_stream(
            ops_sql, parameters=params, settings={"max_block_size": 1024}
        ) as stream:
            for block in stream:
                for (raw,) in block:
                    engine.add(json.loads(raw, parse_float=Decimal))
        finance_only_total = engine.raw_total

        # 4. CIS Buyouts (historical deduplication, Copilot #9)
        snapshots: list[tuple[Any, ...]] = []
        cis_sql = (
            "SELECT account_id, day, payload FROM raw_ozon_cis_buyouts FINAL"
            " WHERE account_id IN {accounts:Array(String)}"
            " AND day >= {start:Date} AND day <= {stop:Date}"
        )
        with contextlib.suppress(Exception):
            snapshots = list(self.ch.query(cis_sql, parameters=params).result_rows)
        if not snapshots:
            daily_sql = (
                "SELECT account_id, day, payload FROM raw_ozon_buyouts_daily FINAL"
                " WHERE account_id IN {accounts:Array(String)}"
                " AND day >= {start:Date} AND day <= {stop:Date}"
            )
            with contextlib.suppress(Exception):
                snapshots = list(self.ch.query(daily_sql, parameters=params).result_rows)

        covered: set[tuple[str, date]] = set()
        for account, day, raw in snapshots:
            day_val = date.fromisoformat(str(day)[:10]) if not isinstance(day, date) else day
            payload = json.loads(raw, parse_float=Decimal)
            engine.add_buyouts(day_val, payload)
            covered.add((str(account), day_val))
            for record in parse_buyouts(payload):
                sku_str = str(record["sku"])
                sku_cards_fallback.setdefault(
                    sku_str,
                    {"offer_id": record["offer_id"], "title": record["title"]},
                )

        requested_days = [
            date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)
        ]
        cis_missing_days = sorted(
            {
                day.isoformat()
                for account in accounts
                for day in requested_days
                if (account, day) not in covered
            }
        )
        cis_complete = not cis_missing_days
        allocated = engine.allocate()

        # 5. Ad linking
        sku_ads: list[tuple[Any, ...]] = []
        ad_sql = (
            "SELECT day, campaign_id, sku, cost FROM raw_ozon_sku_ad_reports FINAL"
            " WHERE account_id IN {accounts:Array(String)}"
            " AND day >= {start:Date} AND day <= {stop:Date}"
        )
        with contextlib.suppress(Exception):
            sku_ads = list(self.ch.query(ad_sql, parameters=params).result_rows)
        if not sku_ads:
            with contextlib.suppress(Exception):
                sku_ads = list(
                    self.ch.query(
                        "SELECT day, campaign_id, sku, cost FROM raw_ozon_ads_sku_daily FINAL"
                        " WHERE account_id IN {accounts:Array(String)}"
                        " AND day >= {start:Date} AND day <= {stop:Date}",
                        parameters=params,
                    ).result_rows
                )
        linked_ads, matched_campaigns = engine.bind_ad_costs(sku_ads)
        if linked_ads:
            allocated["marketing"] = allocated.get("marketing", ZERO) - linked_ads

        # 6. Taxes: scoped strictly to PNL_TAX_ACCOUNT_ID (Copilot #10, #11)
        tax_account_id = os.getenv("PNL_TAX_ACCOUNT_ID", "default")
        tax_enabled = os.getenv(
            "PNL_REALIZATION_TAX_ENABLED", "false"
        ).lower() == "true" and self.org == os.getenv("PNL_TAX_ORGANIZATION_ID", "default")
        rate = number(os.getenv("PNL_TAX_RATE_PCT", "8"))
        taxes: dict[str, Decimal] = {}
        tax_estimate = False

        if tax_enabled and tax_account_id in accounts:
            daily_res = DailyPnlService(self.ch, self.org).build(
                date_from, date_to, "ozon", tax_account_id
            )
            target_tax = sum((number(r["tax"]) for r in daily_res["items"]), ZERO)
            tax_estimate = any(r.get("tax_status") == "estimated" for r in daily_res["items"])
            # Base weights on buyer revenue per SKU
            sku_weights: dict[str, Decimal] = {
                sku: row["buyer_revenue"]
                for sku, row in engine.rows.items()
                if row["buyer_revenue"] > ZERO
            }
            skus = list(sku_weights)
            if not skus and target_tax > ZERO:
                skus = ["unallocated"]
                engine.rows["unallocated"]
                taxes = {"unallocated": target_tax}
            elif skus:
                allocated_taxes = allocate(target_tax, [sku_weights[s] for s in skus])
                taxes = dict(zip(skus, allocated_taxes, strict=True))

        # 7. Additional external expenses
        external = ZERO
        external_unknown = False
        expense_sql = (
            "SELECT month, expense_date, amount_rub FROM dim_additional_expense FINAL"
            " WHERE organization_id={oid:String}"
            " AND month >= toStartOfMonth({start:Date}) AND month <= toStartOfMonth({stop:Date})"
        )
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
            m_date = date.fromisoformat(str(month)[:10]) if not isinstance(month, date) else month
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

        if external or external_unknown:
            engine.rows["unallocated"]

        # 8. Assemble result rows
        items: list[dict[str, Any]] = []
        missing: list[str] = []
        period = (
            date_from.strftime("%d.%m")
            if date_from == date_to
            else f"{date_from:%d.%m.%Y} - {date_to:%d.%m.%Y}"
        )

        for sku, source in engine.rows.items():
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
            # Look up card
            primary_acc = accounts[0] if len(accounts) == 1 else ""
            card = cards.get((primary_acc, sku)) or sku_cards_fallback.get(sku, {})
            offer = card.get("offer_id") or (
                "Расходы без привязки" if sku == "unallocated" else f"SKU {sku}"
            )
            cost = resolve_cost(primary_acc, offer, sku)
            units = r["sales_qty"] + r["returns_qty"] + r["cis_qty"]
            r["cogs"] = cost * units if cost is not None else (ZERO if not units else None)
            if r["cogs"] is None:
                missing.append(offer)
            r["external"] = external if sku == "unallocated" else ZERO
            r["tax"] = taxes.get(sku, ZERO) if tax_enabled else ZERO
            r["tax_main"] = r["tax"]
            r = metric_row(r)
            r.update(
                sku=sku,
                offer_id=offer,
                title=card.get("title") or "",
                image_url=card.get("image_url") or REFERENCE_IMAGES.get(offer),
                period=period,
            )
            if not cis_complete:
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
        total.update(offer_id="Итого", period="Итого", abc="—", sku="total", image_url=None)

        def serial(row: dict[str, Any]) -> dict[str, Any]:
            return {
                k: float(v.quantize(Decimal(".000001"))) if isinstance(v, Decimal) else v
                for k, v in row.items()
            }

        return {
            "items": [serial(r) for r in items],
            "total": serial(total),
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "tax_rate_pct": float(rate),
            "tax_enabled": tax_enabled,
            "tax_estimate": tax_enabled and tax_estimate,
            "missing_costs": missing,
            "operations": engine.operations,
            "source_net_accrued": float(engine.raw_total),
            "source_finance_accruals": float(finance_only_total),
            "cis_buyout_receipts": float(engine.buyout_receipts),
            "cis_coverage_complete": cis_complete,
            "cis_missing_days": cis_missing_days,
            "cis_days_loaded": len(covered),
            "cis_overlap_prevented": engine.buyout_overlap_count,
            "unattributed_costs": {k: float(v) for k, v in allocated.items()},
            "ads_sku_linked": float(linked_ads),
            "ads_campaign_days_linked": matched_campaigns,
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
