"""P&L: indirect expenses and the monthly P&L mart, scoped to one organization."""

from __future__ import annotations

import uuid
import os
import calendar
import json
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
from common.pnl_tax import tax_amount
from common.article_economics import AccrualEconomics

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
_PNL_COLS = (
    "month, organization_id, marketplace, account_id, revenue_rub, commission_rub,"
    " logistics_rub, returns_cost_rub, storage_rub, other_costs_rub, net_accrued_rub, cogs_rub,"
    " gross_profit_rub, ad_cost_rub, additional_expenses_rub,"
    " operating_profit_rub, ebitda_rub, net_profit_rub, margin_pct"
)


class PnlService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def list_expenses(self) -> list[AdditionalExpense]:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, expense_date DESC, category",
            parameters={"oid": self._org},
        )
        return [_row_to_expense(r) for r in rows.named_results()]

    def get_expense(self, expense_id: str) -> AdditionalExpense | None:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE organization_id = {oid:String} AND expense_id = {eid:String} LIMIT 1",
            parameters={"oid": self._org, "eid": expense_id},
        )
        for r in rows.named_results():
            return _row_to_expense(r)
        return None

    def create_expense(self, data: AdditionalExpenseCreate) -> AdditionalExpense:
        now = utc_now()
        expense = AdditionalExpense(
            expense_id=str(uuid.uuid4()),
            organization_id=self._org,
            category=data.category,
            amount_rub=data.amount_rub,
            month=data.month,
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
        elif data.month is not None and existing.expense_date is not None and data.month != existing.month:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="Для переноса дневного расхода укажите expense_date")
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
                " WHERE organization_id = {oid:String} AND expense_id = {eid:String} AND month = {month:Date}",
                parameters={"oid": self._org, "eid": expense_id, "month": f"{existing.month}-01"},
                settings={"mutations_sync": 2},
            )
        return expense

    def delete_expense(self, expense_id: str) -> bool:
        if self.get_expense(expense_id) is None:
            return False
        self._ch.command(
            "ALTER TABLE dim_additional_expense DELETE"
            " WHERE organization_id = {oid:String} AND expense_id = {eid:String}",
            parameters={"oid": self._org, "eid": expense_id},
        )
        return True

    def get_pnl(self, date_from=None, date_to=None, marketplace='', account_id='') -> list[PnlRow]:
        rows = self._ch.query(
            f"SELECT {_PNL_COLS} FROM mrt_pnl_monthly FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, marketplace",
            parameters={"oid": self._org},
            settings=PARTITION_LOCAL_FINAL,
        )
        result = [_row_to_pnl(r) for r in rows.named_results()]
        result = [r for r in result
            if (date_from is None or r.month[:7] >= str(date_from)[:7])
            and (date_to is None or r.month[:7] <= str(date_to)[:7])
            and (not r.marketplace or ((not marketplace or r.marketplace == marketplace)
                 and (not account_id or r.account_id == account_id)))]
        self._apply_financing(result)
        self._apply_cis(result)
        if (os.getenv("PNL_REALIZATION_TAX_ENABLED", "false").lower() == "true"
                and self._org == os.getenv("PNL_TAX_ORGANIZATION_ID", "default")):
            self._apply_realization_tax(result)
        return result

    def _apply_financing(self, rows):
        accounts = sorted({r.account_id for r in rows if r.marketplace == 'ozon'})
        if not accounts:
            return
        amounts = self._ch.query(
            "SELECT toStartOfMonth(day) AS month,account_id,"
            " -sum(details['loans_and_factoring']) AS adjustment"
            " FROM mrt_finance_daily FINAL WHERE marketplace='ozon'"
            " AND account_id IN {accounts:Array(String)}"
            " GROUP BY month,account_id", parameters={'accounts': accounts},
        ).named_results()
        by_key = {(str(r['month'])[:7],r['account_id']):float(r['adjustment']) for r in amounts}
        for row in rows:
            if row.marketplace != 'ozon':
                continue
            adjustment = by_key.get((row.month[:7],row.account_id),0)
            row.financing_adjustment_rub = adjustment
            row.other_costs_rub -= adjustment
            for field in ('net_accrued_rub','gross_profit_rub','operating_profit_rub','ebitda_rub','net_profit_rub'):
                value = getattr(row,field)
                if value is not None:
                    setattr(row,field,value+adjustment)

    def _apply_cis(self, rows):
        from app.services.ozon_cis_service import cis_adjustments
        self._cis_receipts = {}
        for row in rows:
            if row.marketplace != 'ozon':
                continue
            account_id = row.account_id
            year, month_number = map(int, row.month[:7].split('-'))
            first = date(year, month_number, 1)
            last = date(year, month_number, calendar.monthrange(year, month_number)[1])
            adjustments = cis_adjustments(self._ch, account_id, first, last)
            receipts = sum((v['receipts'] for v in adjustments.values()), Decimal(0))
            cogs = sum((v['cogs'] for v in adjustments.values()), Decimal(0))
            row.revenue_rub += float(sum(v['revenue'] for v in adjustments.values()))
            row.commission_rub += float(sum(v['commission'] for v in adjustments.values()))
            row.net_accrued_rub += float(receipts)
            row.cogs_rub += float(cogs)
            for field in ('gross_profit_rub','operating_profit_rub','ebitda_rub','net_profit_rub'):
                value = getattr(row, field)
                if value is not None:
                    setattr(row, field, value+float(receipts-cogs))
            self._cis_receipts[(row.month[:7], account_id)] = receipts

    def _apply_realization_tax(self, rows: list[PnlRow]) -> None:
        account_id = os.getenv("PNL_TAX_ACCOUNT_ID", "default")
        rate = Decimal(os.getenv("PNL_TAX_RATE_PCT", "8"))
        reports = self._ch.query(
            "SELECT month, sales_amount - returns_amount AS tax_base, fetched_at"
            " FROM raw_ozon_realization_monthly FINAL WHERE account_id = {aid:String}",
            parameters={"aid": account_id},
        )
        by_month = {str(r['month'])[:7]: r for r in reports.named_results()}
        coverage = self._ch.query(
            "SELECT toStartOfMonth(day) AS month, uniqExact(day) AS days"
            " FROM raw_ozon_finance_balance FINAL WHERE account_id = {aid:String} GROUP BY month",
            parameters={"aid": account_id},
        )
        days = {str(r['month'])[:7]: int(r['days']) for r in coverage.named_results()}
        for row in rows:
            if row.marketplace != 'ozon' or row.account_id != account_id:
                continue
            receipts = getattr(self, '_cis_receipts', {}).get((row.month[:7], account_id), Decimal(0))
            row.tax_enabled = True
            row.tax_rate_pct = float(rate)
            row.profit_before_tax_rub = row.net_profit_rub
            month = row.month[:7]
            report = by_month.get(month)
            if report is None:
                # Preliminary base uses sales net of returns, before marketplace
                # deductions. A subsequently collected report replaces it on read.
                base = self._buyer_tax_base(account_id, month)
                tax = tax_amount(base, rate)
                row.tax_base_rub = float(base)
                row.tax_rub = float(tax)
                row.tax_status = 'estimated'
                row.net_profit_rub = float((Decimal(str(row.profit_before_tax_rub)) - tax).quantize(Decimal('0.01')))
                continue
            base = Decimal(str(report['tax_base'])) + receipts
            tax = tax_amount(base, rate)
            row.tax_base_rub = float(base)
            row.tax_rub = float(tax)
            row.realization_fetched_at = str(report['fetched_at'])
            year, month_number = map(int, month.split('-'))
            if days.get(month, 0) != calendar.monthrange(year, month_number)[1]:
                base = self._buyer_tax_base(account_id, month)
                tax = tax_amount(base, rate)
                row.tax_base_rub = float(base)
                row.tax_rub = float(tax)
                row.tax_status = 'estimated'
                row.net_profit_rub = float((Decimal(str(row.profit_before_tax_rub)) - tax).quantize(Decimal('0.01')))
            else:
                row.tax_status = 'confirmed'
                row.net_profit_rub = float((Decimal(str(row.profit_before_tax_rub)) - tax).quantize(Decimal('0.01')))

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
            engine.add(json.loads(record['payload'], parse_float=Decimal))
        for record in self._ch.query(
            "SELECT day,payload FROM raw_ozon_buyouts_daily FINAL"
            " WHERE account_id={aid:String} AND day>={month:Date}"
            " AND day<addMonths({month:Date},1)", parameters=params,
        ).named_results():
            engine.add_buyouts(record['day'], json.loads(record['payload'], parse_float=Decimal))
        return sum((r['buyer_revenue'] for r in engine.rows.values()), Decimal(0))

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


def _row_to_pnl(r: dict[str, Any]) -> PnlRow:
    return PnlRow(
        month=str(r["month"]),
        organization_id=r["organization_id"],
        marketplace=r["marketplace"],
        account_id=r["account_id"],
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
