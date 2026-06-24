from __future__ import annotations

from typing import Any

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.organization import OrgMemberRole
from app.services.abc_xyz_service import AbcXyzService
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/abc-xyz", tags=["abc-xyz"], responses=API_ERROR_RESPONSES)


@router.get("")
def get_abc_xyz(
    ch: ChClientDependency,
    marketplace: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.manager)),
) -> list[dict[str, Any]]:
    return AbcXyzService(ch).get_analysis(marketplace, account_id)
