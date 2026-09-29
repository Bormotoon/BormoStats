from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import AdminAuth, AuthContext, ManagerAuth
from app.core.deps import ChClientDependency
from app.models.pnl import (
    AdditionalExpense,
    AdditionalExpenseCreate,
    AdditionalExpenseUpdate,
    PnlRow,
)
from app.services.pnl_service import PnlService
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/pnl", tags=["pnl"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency, auth: AuthContext) -> PnlService:
    return PnlService(ch, auth.organization_id)


@router.get("")
def get_pnl(ch: ChClientDependency, auth: ManagerAuth) -> list[PnlRow]:
    return _svc(ch, auth).get_pnl()


@router.get("/expenses")
def list_expenses(ch: ChClientDependency, auth: ManagerAuth) -> list[AdditionalExpense]:
    return _svc(ch, auth).list_expenses()


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
def create_expense(
    body: AdditionalExpenseCreate,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> AdditionalExpense:
    return _svc(ch, auth).create_expense(body)


@router.patch("/expenses/{expense_id}")
def update_expense(
    expense_id: str,
    body: AdditionalExpenseUpdate,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> AdditionalExpense:
    exp = _svc(ch, auth).update_expense(expense_id, body)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="expense not found")
    return exp


@router.delete("/expenses/{expense_id}")
def delete_expense(
    expense_id: str,
    ch: ChClientDependency,
    auth: AdminAuth,
) -> dict[str, bool]:
    if not _svc(ch, auth).delete_expense(expense_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="expense not found")
    return {"deleted": True}
