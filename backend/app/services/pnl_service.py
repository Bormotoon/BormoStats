"""P&L data access: additional expenses and monthly P&L view."""

from __future__ import annotations

import calendar
import json
import os
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.db.ch import PARTITION_LOCAL_FINAL, insert_values_sql, utc_now
from app.models.pnl import (
    AdditionalExpense,
    AdditionalExpenseCreate,
    AdditionalExpenseUpdate,
    PnlRow,
)
from clickhouse_connect.driver import Client
from fastapi import HTTPException

from common.article_economics import AccrualEconomics
from common.pnl_tax import is_tax_applicable, tax_amount

_EXP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("expense_id", "String"),
    ("organization_id", "String"),
    ("category", "String"),
    ("amount_rub", "Float64"),
    ("month", "Date"),
    ("expense_date", "Nullable(Date)"),
    ("description", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)

_EXP_COLS = ", ".join(name for name, _ in _EXP_COLUMNS)
_EXP_INSERT = insert_values_sql("dim_additional_expense", _EXP_COLUMNS)


class PnlService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id
        self._cis_receipts: dict[tuple[str, str], Decimal] = {}

    def list_expenses(self) -> list[AdditionalExpense]:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE organization_id = {oid:String}"
            " ORDER BY month DESC, expense_date DESC, category",
            parameters={"oid": self._org},
        )
        return [_row_to_expense(r) for r in rows.named_results()]

    def get_expense(self, expense_id: str) -> AdditionalExpense | None:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE organization_id = {oid:String} AND expense_id = {eid:String}",
            parameters={"oid": self._org, "eid": expense_id},
        )
        res = list(rows.named_results())
        return _row_to_expense(res[0]) if res else None

    def create_expense(self, data: AdditionalExpenseCreate) -> AdditionalExpense:
        now = utc_now()
        month_val = (
            data.expense_date.strftime("%Y-%m")
            if data.expense_date is not None
            else (data.month or "")
        )
        expense = AdditionalExpense(
            expense_id=str(uuid.uuid4()),
            organization_id=self._org,
            category=data.category,
            amount_rub=data.amount_rub,
            month=month_val,
            expense_date=data.expense_date,
            description=data.description,
            created_at=now,
            updated_at=now,
        )
        self._write(expense)
        return expense

    def update_expense(
        self, expense_id: str, data: AdditionalExpenseUpdate
    ) -> AdditionalExpense | None:
        existing = self.get_expense(expense_id)
        if existing is None:
            return None
        now = utc_now()
        changes = data.model_dump(exclude_none=True)
        if data.expense_date is not None:
            changes["month"] = data.expense_date.strftime("%Y-%m")
        elif (
            data.month is not None
            and existing.expense_date is not None
            and data.month != existing.month
        ):
            raise HTTPException(
                status_code=422, detail="Для переноса дневного расхода укажите expense_date"
            )
        expense = existing.model_copy(
            update={
                **changes,
                "created_at": existing.created_at or now,
                "updated_at": now,
            }
        )
        self._write(expense)
        if expense.month != existing.month:
            # month is part of the replacement key: remove the old key after moving.
            self._ch.command(
                "ALTER TABLE dim_additional_expense DELETE"
                " WHERE organization_id = {oid:String} AND expense_id = {eid:String}"
                " AND month = {month:Date}",
                parameters={"oid": self._org, "eid": expense_id, "month": f"{existing.month}-01"},
                settings={"mutations_sync": 2},
            )
        return expense

    def delete_expense(self, expense_id: str) -> bool:
        existing = self.get_expense(expense_id)
        if existing is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_additional_expense DELETE"
            " WHERE organization_id = {oid:String} AND expense_id = {eid:String}",
            parameters={"oid": self._org, "eid": expense_id},
            settings={"mutations_sync": 2},
        )
        return True

    def get_pnl(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        marketplace: str = "",
        account_id: str = "",
    ) -> list[PnlRow]:
        rows = self._ch.query(
            f"SELECT {_PNL_COLS} FROM mrt_pnl_monthly FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, marketplace",
            parameters={"oid": self._org},
            settings=PARTITION_LOCAL_FINAL,
        )
        result = [_row_to_pnl(r) for r in rows.named_results()]
        result = [
            r
            for r in result
            if (date_from is None or r.month[:7] >= str(date_from)[:7])
            and (date_to is None or r.month[:7] <= str(date_to)[:7])
            and (
                not r.marketplace
                or (
                    (not marketplace or r.marketplace == marketplace)
                    and (not account_id or r.account_id == account_id)
                )
            )
        ]
        self._apply_financing(result)
        self._apply_cis(result)
        if os.getenv(
            "PNL_REALIZATION_TAX_ENABLED", "false"
        ).lower() == "true" and self._org == os.getenv("PNL_TAX_ORGANIZATION_ID", "default"):
            self._apply_realization_tax(result)
        return result

    def _apply_financing(self, rows: list[PnlRow]) -> None:
        accounts = sorted({r.account_id for r in rows if r.marketplace == "ozon"})
        if not accounts:
            return
        amounts = self._ch.query(
            "SELECT toStartOfMonth(day) AS month, account_id,"
            " -sum(details['loans_and_factoring']) AS adjustment"
            " FROM mrt_finance_daily FINAL WHERE marketplace='ozon'"
            " AND account_id IN {accounts:Array(String)}"
            " GROUP BY month, account_id",
            parameters={"accounts": accounts},
        ).named_results()
        by_key = {(str(r["month"])[:7], r["account_id"]): float(r["adjustment"]) for r in amounts}
        for row in rows:
            if row.marketplace != "ozon":
                continue
            adjustment = by_key.get((row.month[:7], row.account_id), 0.0)
            row.financing_adjustment_rub = adjustment
            row.other_costs_rub -= adjustment
            for field in (
                "net_accrued_rub",
                "gross_profit_rub",
                "operating_profit_rub",
                "ebitda_rub",
                "net_profit_rub",
            ):
                value = getattr(row, field)
                if value is not None:
                    setattr(row, field, value + adjustment)
            net_rev = row.revenue_rub - row.returns_cost_rub
            row.margin_pct = (
                round((row.gross_profit_rub / net_rev) * 100.0, 2) if net_rev > 0 else 0.0
            )

    def _apply_cis(self, rows: list[PnlRow]) -> None:
        from app.services.ozon_cis_service import cis_adjustments

        self._cis_receipts = {}
        for row in rows:
            if row.marketplace != "ozon":
                continue
            account_id = row.account_id
            year, month_number = map(int, row.month[:7].split("-"))
            first = date(year, month_number, 1)
            last = date(year, month_number, calendar.monthrange(year, month_number)[1])
            adjustments = cis_adjustments(self._ch, account_id, first, last)
            receipts = sum((v["receipts"] for v in adjustments.values()), Decimal(0))
            cogs = sum((v["cogs"] for v in adjustments.values()), Decimal(0))
            row.revenue_rub += float(sum(v["revenue"] for v in adjustments.values()))
            row.commission_rub += float(sum(v["commission"] for v in adjustments.values()))
            row.net_accrued_rub += float(receipts)
            row.cogs_rub += float(cogs)
            for field in (
                "gross_profit_rub",
                "operating_profit_rub",
                "ebitda_rub",
                "net_profit_rub",
            ):
                value = getattr(row, field)
                if value is not None:
                    setattr(row, field, value + float(receipts - cogs))
            self._cis_receipts[(row.month[:7], account_id)] = receipts
            net_rev = row.revenue_rub - row.returns_cost_rub
            row.margin_pct = (
                round((row.gross_profit_rub / net_rev) * 100.0, 2) if net_rev > 0 else 0.0
            )

    def _apply_realization_tax(self, rows: list[PnlRow]) -> None:
        applicable_rows = [
            row for row in rows if is_tax_applicable(self._org, row.marketplace, row.account_id)
        ]
        if not applicable_rows:
            return

        rate = Decimal(os.getenv("PNL_TAX_RATE_PCT", "8"))
        today = date.today()

        ozon_rows = [r for r in applicable_rows if r.marketplace == "ozon"]
        ozon_reports: dict[tuple[str, str], dict[str, Any]] = {}
        ozon_days: dict[tuple[str, str], int] = {}
        if ozon_rows:
            ozon_aids = sorted({r.account_id for r in ozon_rows})
            for aid in ozon_aids:
                reports = self._ch.query(
                    "SELECT month, sum(sale_amount) - sum(return_amount) AS tax_base,"
                    " max(ingested_at) AS fetched_at"
                    " FROM raw_ozon_realization_reports FINAL WHERE account_id = {aid:String}"
                    " GROUP BY month",
                    parameters={"aid": aid},
                )
                for r in reports.named_results():
                    ozon_reports[(aid, str(r["month"])[:7])] = r
                coverage = self._ch.query(
                    "SELECT toStartOfMonth(day) AS month, uniqExact(day) AS days"
                    " FROM raw_ozon_finance_balance FINAL"
                    " WHERE account_id = {aid:String} GROUP BY month",
                    parameters={"aid": aid},
                )
                for r in coverage.named_results():
                    ozon_days[(aid, str(r["month"])[:7])] = int(r["days"])

        wb_rows = [r for r in applicable_rows if r.marketplace == "wb"]
        wb_reports: dict[tuple[str, str], dict[str, Any]] = {}
        wb_fallback: dict[tuple[str, str], Decimal] = {}
        if wb_rows:
            wb_aids = sorted({r.account_id for r in wb_rows})
            wb_months = sorted({f"{r.month[:7]}-01" for r in wb_rows})
            wb_query = (
                "SELECT account_id, toStartOfMonth(day) AS month, count() AS rows_cnt, "
                "sum(multiIf("
                "lowerUTF8(JSONExtractString(payload, 'doc_type_name')) LIKE 'продаж%', "
                "toDecimal64OrZero(toString(JSONExtractRaw(payload, 'retail_amount')), 2), "
                "lowerUTF8(JSONExtractString(payload, 'doc_type_name')) LIKE 'возврат%', "
                "-abs(toDecimal64OrZero(toString(JSONExtractRaw(payload, 'retail_amount')), 2)), "
                "toDecimal64(0, 2)"
                ")) AS retail_base, "
                "max(ingested_at) AS fetched_at "
                "FROM raw_wb_finance_report FINAL "
                "WHERE account_id IN {aids:Array(String)} "
                "AND toStartOfMonth(day) IN {months:Array(Date)} "
                "GROUP BY account_id, month"
            )
            for r in self._ch.query(
                wb_query, parameters={"aids": wb_aids, "months": wb_months}
            ).named_results():
                wb_reports[(r["account_id"], str(r["month"])[:7])] = r

            needs_fallback_aids = [
                r.account_id
                for r in wb_rows
                if (r.account_id, r.month[:7]) not in wb_reports
                or wb_reports[(r.account_id, r.month[:7])]["rows_cnt"] <= 0
            ]
            if needs_fallback_aids:
                wb_finance_query = (
                    "SELECT account_id, toStartOfMonth(day) AS month, "
                    "sum(sales + returns) AS revenue_base "
                    "FROM mrt_finance_daily FINAL "
                    "WHERE marketplace = 'wb' AND account_id IN {aids:Array(String)} "
                    "AND toStartOfMonth(day) IN {months:Array(Date)} "
                    "GROUP BY account_id, month"
                )
                for r in self._ch.query(
                    wb_finance_query,
                    parameters={"aids": sorted(set(needs_fallback_aids)), "months": wb_months},
                ).named_results():
                    wb_fallback[(r["account_id"], str(r["month"])[:7])] = Decimal(
                        str(r["revenue_base"])
                    )

        ym_rows = [r for r in applicable_rows if r.marketplace == "ym"]
        ym_finance: dict[tuple[str, str], dict[str, Any]] = {}
        if ym_rows:
            ym_aids = sorted({r.account_id for r in ym_rows})
            ym_months = sorted({f"{r.month[:7]}-01" for r in ym_rows})
            ym_query = (
                "SELECT account_id, toStartOfMonth(day) AS month, "
                "sum(sales + returns) AS revenue_base, "
                "countIf(sales != 0 OR returns != 0 OR net_accrued != 0) AS tx_cnt "
                "FROM mrt_finance_daily FINAL "
                "WHERE marketplace = 'ym' AND account_id IN {aids:Array(String)} "
                "AND toStartOfMonth(day) IN {months:Array(Date)} "
                "GROUP BY account_id, month"
            )
            for r in self._ch.query(
                ym_query, parameters={"aids": ym_aids, "months": ym_months}
            ).named_results():
                ym_finance[(r["account_id"], str(r["month"])[:7])] = r

        for row in rows:
            if not is_tax_applicable(self._org, row.marketplace, row.account_id):
                continue

            row.tax_enabled = True
            row.tax_rate_pct = float(rate)
            row.profit_before_tax_rub = row.net_profit_rub
            month = row.month[:7]
            year, month_number = map(int, month.split("-"))
            last_day_of_month = date(year, month_number, calendar.monthrange(year, month_number)[1])
            is_month_closed = last_day_of_month < today

            if row.marketplace == "ozon":
                receipts = getattr(self, "_cis_receipts", {}).get(
                    (row.month[:7], row.account_id), Decimal(0)
                )
                report = ozon_reports.get((row.account_id, month))
                if report is None:
                    base = self._buyer_tax_base(row.account_id, month)
                    tax = tax_amount(base, rate)
                    row.tax_base_rub = float(base)
                    row.tax_rub = float(tax)
                    row.tax_status = "estimated"
                    row.net_profit_rub = float(
                        (Decimal(str(row.profit_before_tax_rub)) - tax).quantize(Decimal("0.01"))
                    )
                else:
                    base = Decimal(str(report["tax_base"])) + receipts
                    tax = tax_amount(base, rate)
                    row.tax_base_rub = float(base)
                    row.tax_rub = float(tax)
                    row.realization_fetched_at = str(report["fetched_at"])
                    if (
                        ozon_days.get((row.account_id, month), 0)
                        != calendar.monthrange(year, month_number)[1]
                    ):
                        base = self._buyer_tax_base(row.account_id, month)
                        tax = tax_amount(base, rate)
                        row.tax_base_rub = float(base)
                        row.tax_rub = float(tax)
                        row.tax_status = "estimated"
                        row.net_profit_rub = float(
                            (Decimal(str(row.profit_before_tax_rub)) - tax).quantize(
                                Decimal("0.01")
                            )
                        )
                    else:
                        row.tax_status = "confirmed"
                        row.net_profit_rub = float(
                            (Decimal(str(row.profit_before_tax_rub)) - tax).quantize(
                                Decimal("0.01")
                            )
                        )

            elif row.marketplace == "wb":
                wb_rep = wb_reports.get((row.account_id, month))
                if wb_rep is not None and wb_rep["rows_cnt"] > 0:
                    base = Decimal(str(wb_rep["retail_base"]))
                    tax = tax_amount(base, rate)
                    row.tax_base_rub = float(base)
                    row.tax_rub = float(tax)
                    if wb_rep.get("fetched_at"):
                        row.realization_fetched_at = str(wb_rep["fetched_at"])
                    row.tax_status = "confirmed" if is_month_closed else "estimated"
                else:
                    base = wb_fallback.get(
                        (row.account_id, month),
                        Decimal(str(row.revenue_rub)) - Decimal(str(row.returns_cost_rub)),
                    )
                    tax = tax_amount(base, rate)
                    row.tax_base_rub = float(base)
                    row.tax_rub = float(tax)
                    row.tax_status = "estimated"
                row.net_profit_rub = float(
                    (Decimal(str(row.profit_before_tax_rub)) - tax).quantize(Decimal("0.01"))
                )

            elif row.marketplace == "ym":
                ym_data = ym_finance.get((row.account_id, month))
                if ym_data is not None:
                    base = Decimal(str(ym_data["revenue_base"]))
                    has_tx = ym_data["tx_cnt"] > 0
                else:
                    base = Decimal(str(row.revenue_rub)) - Decimal(str(row.returns_cost_rub))
                    has_tx = row.revenue_rub != 0 or row.net_accrued_rub != 0

                tax = tax_amount(base, rate)
                row.tax_base_rub = float(base)
                row.tax_rub = float(tax)
                row.tax_status = "confirmed" if (is_month_closed and has_tx) else "estimated"
                row.net_profit_rub = float(
                    (Decimal(str(row.profit_before_tax_rub)) - tax).quantize(Decimal("0.01"))
                )

            net_rev = row.revenue_rub - row.returns_cost_rub
            base_rev = net_rev if net_rev > 0 else row.revenue_rub
            row.margin_pct = (
                round((row.gross_profit_rub / base_rev) * 100.0, 2) if base_rev > 0 else 0.0
            )

    def _buyer_tax_base(self, account_id: str, month: str) -> Decimal:
        """Buyer receipts net of returns, using the same sources as article economics."""
        params = {"aid": account_id, "month": month + "-01"}
        engine = AccrualEconomics()
        for record in self._ch.query(
            "SELECT payload FROM raw_ozon_finance_ops FINAL"
            " WHERE account_id={aid:String} AND source='accrual_by_day'"
            " AND operation_ts>=toDateTime({month:Date}, 'Europe/Moscow')"
            " AND operation_ts<toDateTime(addMonths({month:Date},1), 'Europe/Moscow')",
            parameters=params,
        ).named_results():
            engine.add(json.loads(record["payload"], parse_float=Decimal))
        try:
            buyouts = self._ch.query(
                "SELECT day, sku, offer_id, title, price, quantity, amount, payload "
                "FROM raw_ozon_cis_buyouts FINAL "
                "WHERE account_id={aid:String} AND day>={month:Date} "
                "AND day<addMonths({month:Date},1)",
                parameters=params,
            ).named_results()
        except Exception:
            buyouts = self._ch.query(
                "SELECT day, payload FROM raw_ozon_cis_buyouts FINAL "
                "WHERE account_id={aid:String} AND day>={month:Date} "
                "AND day<addMonths({month:Date},1)",
                parameters=params,
            ).named_results()
        for record in buyouts:
            raw = record.get("payload")
            if raw and isinstance(raw, str) and raw.strip().startswith("{"):
                engine.add_buyouts(record["day"], json.loads(raw, parse_float=Decimal))
            elif record.get("sku"):
                posting = str(record.get("offer_id") or record.get("sku"))
                sku = str(record["sku"])
                qty = Decimal(str(record.get("quantity") or 1))
                price = Decimal(str(record.get("price") or 0))
                amt = Decimal(str(record.get("amount") or 0))
                p_obj = {
                    "products": [
                        {
                            "sku": sku,
                            "posting_number": posting,
                            "offer_id": str(record.get("offer_id") or ""),
                            "name": str(record.get("title") or ""),
                            "quantity": qty,
                            "seller_price_per_instance": price,
                            "amount": amt,
                        }
                    ]
                }
                engine.add_buyouts(record["day"], p_obj)
        return sum((r["buyer_revenue"] for r in engine.rows.values()), Decimal(0))

    def _write(self, expense: AdditionalExpense) -> None:
        self._ch.command(
            _EXP_INSERT,
            parameters={
                "expense_id": expense.expense_id,
                "organization_id": expense.organization_id,
                "category": expense.category,
                "amount_rub": expense.amount_rub,
                "month": f"{expense.month}-01",
                "expense_date": expense.expense_date,
                "description": expense.description,
                "created_at": expense.created_at,
                "updated_at": expense.updated_at,
            },
        )


def _row_to_expense(r: dict[str, Any]) -> AdditionalExpense:
    return AdditionalExpense(
        expense_id=r["expense_id"],
        organization_id=r["organization_id"],
        category=r["category"],
        amount_rub=float(r["amount_rub"]),
        month=str(r["month"])[:7],
        expense_date=r.get("expense_date"),
        description=r["description"],
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


_PNL_COLS = (
    "month, organization_id, marketplace, account_id, revenue_rub, commission_rub, "
    "logistics_rub, returns_cost_rub, storage_rub, other_costs_rub, net_accrued_rub, "
    "cogs_rub, gross_profit_rub, ad_cost_rub, additional_expenses_rub, "
    "operating_profit_rub, ebitda_rub, net_profit_rub, margin_pct"
)


def _row_to_pnl(r: dict[str, Any]) -> PnlRow:
    return PnlRow(
        month=str(r["month"])[:7],
        organization_id=r["organization_id"],
        marketplace=r.get("marketplace", ""),
        account_id=r.get("account_id", ""),
        revenue_rub=float(r["revenue_rub"]),
        commission_rub=float(r["commission_rub"]),
        logistics_rub=float(r["logistics_rub"]),
        returns_cost_rub=float(r["returns_cost_rub"]),
        storage_rub=float(r["storage_rub"]),
        other_costs_rub=float(r["other_costs_rub"]),
        net_accrued_rub=float(r["net_accrued_rub"]),
        cogs_rub=float(r["cogs_rub"]),
        gross_profit_rub=float(r["gross_profit_rub"]),
        ad_cost_rub=float(r["ad_cost_rub"]),
        additional_expenses_rub=float(r["additional_expenses_rub"]),
        operating_profit_rub=float(r["operating_profit_rub"]),
        ebitda_rub=float(r["ebitda_rub"]),
        net_profit_rub=float(r["net_profit_rub"]),
        margin_pct=float(r["margin_pct"]),
    )
