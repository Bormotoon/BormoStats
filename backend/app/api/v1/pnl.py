from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.organization import OrgMemberRole
from app.models.pnl import (
    AdditionalExpense,
    AdditionalExpenseCreate,
    AdditionalExpenseUpdate,
    PnlRow,
)
from app.services.pnl_service import PnlService
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/pnl", tags=["pnl"], responses=API_ERROR_RESPONSES)


def _svc(ch: ChClientDependency) -> PnlService:
    return PnlService(ch)


@router.get("")
def get_pnl(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[PnlRow]:
    return _svc(ch).get_pnl()


@router.get("/expenses")
def list_expenses(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[AdditionalExpense]:
    return _svc(ch).list_expenses()


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
def create_expense(
    body: AdditionalExpenseCreate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> AdditionalExpense:
    return _svc(ch).create_expense(body)


@router.patch("/expenses/{expense_id}")
def update_expense(
    expense_id: str,
    body: AdditionalExpenseUpdate,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> AdditionalExpense:
    exp = _svc(ch).update_expense(expense_id, body)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="expense not found")
    return exp


@router.delete("/expenses/{expense_id}")
def delete_expense(
    expense_id: str,
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.admin)),
) -> dict[str, bool]:
    _svc(ch).delete_expense(expense_id)
    return {"deleted": True}
