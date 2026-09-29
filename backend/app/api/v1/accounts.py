from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import ViewerAuth
from app.core.deps import ChClientDependency
from app.services.tenancy import list_organization_accounts
from fastapi import APIRouter

router = APIRouter(prefix="/accounts", tags=["accounts"], responses=API_ERROR_RESPONSES)


@router.get("")
def list_accounts(ch: ChClientDependency, auth: ViewerAuth) -> list[dict[str, str]]:
    """Marketplace accounts that belong to the caller's organization."""
    return list_organization_accounts(ch, auth.organization_id)
