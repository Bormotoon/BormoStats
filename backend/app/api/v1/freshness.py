from __future__ import annotations

from typing import Any

from app.api.errors import API_ERROR_RESPONSES
from app.core.auth import ViewerAuth
from app.core.deps import ChClientDependency
from app.services.freshness_service import FreshnessService
from fastapi import APIRouter

router = APIRouter(prefix="/freshness", tags=["freshness"], responses=API_ERROR_RESPONSES)


@router.get("")
def data_freshness(ch: ChClientDependency, auth: ViewerAuth) -> dict[str, Any]:
    """Last mart rebuild, collector watermarks and recent source errors for the caller's org."""
    return FreshnessService(ch, auth.organization_id).summary()
