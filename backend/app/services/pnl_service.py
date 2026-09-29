"""P&L: indirect expenses and the monthly P&L mart, scoped to one organization."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.ch import PARTITION_LOCAL_FINAL, insert_values_sql, utc_now
from app.models.pnl import (
    AdditionalExpense,
    AdditionalExpenseCreate,
    AdditionalExpenseUpdate,
    PnlRow,
)
from clickhouse_connect.driver import Client

_EXP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("expense_id", "String"),
    ("organization_id", "String"),
    ("category", "String"),
    ("amount_rub", "Float64"),
    ("month", "Date"),
    ("description", "String"),
    ("created_at", "DateTime"),
    ("updated_at", "DateTime"),
)
_EXP_COLS = ", ".join(name for name, _ in _EXP_COLUMNS)
_EXP_INSERT = insert_values_sql("dim_additional_expense", _EXP_COLUMNS)
_PNL_COLS = (
    "month, organization_id, marketplace, account_id, revenue_rub, commission_rub,"
    " logistics_rub, returns_cost_rub, gross_profit_rub, ad_cost_rub, additional_expenses_rub,"
    " operating_profit_rub, ebitda_rub, net_profit_rub, margin_pct"
)


class PnlService:
    def __init__(self, ch: Client, organization_id: str) -> None:
        self._ch = ch
        self._org = organization_id

    def list_expenses(self) -> list[AdditionalExpense]:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, category",
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
        expense = existing.model_copy(
            update={
                **data.model_dump(exclude_none=True),
                "created_at": existing.created_at or now,
                "updated_at": now,
            }
        )
        self._write(expense)
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

    def get_pnl(self) -> list[PnlRow]:
        rows = self._ch.query(
            f"SELECT {_PNL_COLS} FROM mrt_pnl_monthly FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, marketplace",
            parameters={"oid": self._org},
            settings=PARTITION_LOCAL_FINAL,
        )
        return [_row_to_pnl(r) for r in rows.named_results()]

    def _write(self, expense: AdditionalExpense) -> None:
        self._ch.command(
            _EXP_INSERT,
            parameters={
                "expense_id": expense.expense_id,
                "organization_id": expense.organization_id,
                "category": expense.category,
                "amount_rub": expense.amount_rub,
                "month": f"{expense.month}-01",
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
        gross_profit_rub=float(r["gross_profit_rub"]),
        ad_cost_rub=float(r["ad_cost_rub"]),
        additional_expenses_rub=float(r["additional_expenses_rub"]),
        operating_profit_rub=float(r["operating_profit_rub"]),
        ebitda_rub=float(r["ebitda_rub"]),
        net_profit_rub=float(r["net_profit_rub"]),
        margin_pct=float(r["margin_pct"]),
    )
