from __future__ import annotations

from typing import Any

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import ManagerAuth
from app.core.deps import ChClientDependency
from app.services.abc_xyz_service import AbcXyzService
from fastapi import APIRouter, Query

router = APIRouter(prefix="/abc-xyz", tags=["abc-xyz"], responses=API_ERROR_RESPONSES)


@router.get("")
def get_abc_xyz(
    ch: ChClientDependency,
    auth: ManagerAuth,
    marketplace: str | None = Query(default=None, pattern=r"^(wb|ozon)$"),
    account_id: str | None = Query(default=None, max_length=64),
) -> list[dict[str, Any]]:
    return AbcXyzService(ch, auth.organization_id).get_analysis(marketplace, account_id)
