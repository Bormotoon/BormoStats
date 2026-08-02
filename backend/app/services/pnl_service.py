from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.pnl import (
    AdditionalExpense,
    AdditionalExpenseCreate,
    AdditionalExpenseUpdate,
    PnlRow,
)
from clickhouse_connect.driver import Client

_EXP_COLS = (
    "expense_id, organization_id, category, amount_rub, month, description, created_at, updated_at"
)
_EXP_INSERT = (
    "INSERT INTO dim_additional_expense ({cols})"
    " VALUES ({eid:String}, {oid:String}, {cat:String}, {amt:Float64},"
    " {month:Date}, {desc:String}, {created:DateTime}, {now:DateTime})"
)

_PNL_COLS = (
    "month, organization_id, marketplace, account_id, revenue_rub, commission_rub, "
    "logistics_rub, returns_cost_rub, gross_profit_rub, ad_cost_rub, "
    "additional_expenses_rub, operating_profit_rub, ebitda_rub, net_profit_rub, margin_pct"
)


class PnlService:
    def __init__(self, ch: Client) -> None:
        self._ch = ch

    def list_expenses(self, organization_id: str = "default") -> list[AdditionalExpense]:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, category",
            parameters={"oid": organization_id},
        )
        return [_row_to_expense(r) for r in rows.named_results()]

    def create_expense(self, data: AdditionalExpenseCreate) -> AdditionalExpense:
        now = datetime.utcnow()
        eid = str(uuid.uuid4())[:8]
        self._ch.command(
            _EXP_INSERT.format(cols=_EXP_COLS),
            parameters={
                "eid": eid,
                "oid": data.organization_id,
                "cat": data.category,
                "amt": data.amount_rub,
                "month": data.month + "-01",
                "desc": data.description,
                "created": now,
                "now": now,
            },
        )
        return AdditionalExpense(
            expense_id=eid,
            organization_id=data.organization_id,
            category=data.category,
            amount_rub=data.amount_rub,
            month=data.month,
            description=data.description,
            created_at=now,
            updated_at=now,
        )

    def update_expense(
        self, expense_id: str, data: AdditionalExpenseUpdate
    ) -> AdditionalExpense | None:
        rows = self._ch.query(
            f"SELECT {_EXP_COLS} FROM dim_additional_expense FINAL"
            " WHERE expense_id = {eid:String}",
            parameters={"eid": expense_id},
        )
        existing = None
        for r in rows.named_results():
            existing = _row_to_expense(r)
        if existing is None:
            return None
        now = datetime.utcnow()
        category = data.category if data.category is not None else existing.category
        amount = data.amount_rub if data.amount_rub is not None else existing.amount_rub
        month = data.month if data.month is not None else existing.month
        desc = data.description if data.description is not None else existing.description
        self._ch.command(
            _EXP_INSERT.format(cols=_EXP_COLS),
            parameters={
                "eid": expense_id,
                "oid": existing.organization_id,
                "cat": category,
                "amt": amount,
                "month": month + "-01",
                "desc": desc,
                "created": existing.created_at or now,
                "now": now,
            },
        )
        return AdditionalExpense(
            expense_id=expense_id,
            organization_id=existing.organization_id,
            category=category,
            amount_rub=amount,
            month=month,
            description=desc,
            created_at=existing.created_at or now,
            updated_at=now,
        )

    def delete_expense(self, expense_id: str) -> bool:
        self._ch.command(
            "ALTER TABLE dim_additional_expense DELETE WHERE expense_id = %(eid)s",
            parameters={"eid": expense_id},
        )
        return True

    def get_pnl(self, organization_id: str = "default") -> list[PnlRow]:
        rows = self._ch.query(
            f"SELECT {_PNL_COLS} FROM mrt_pnl_monthly FINAL"
            " WHERE organization_id = {oid:String} ORDER BY month DESC, marketplace",
            parameters={"oid": organization_id},
        )
        return [_row_to_pnl(r) for r in rows.named_results()]


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
