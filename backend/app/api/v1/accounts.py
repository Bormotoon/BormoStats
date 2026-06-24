from __future__ import annotations

from app.api.errors import API_ERROR_RESPONSES
from app.core.deps import ChClientDependency, require_admin_key_or_org_role
from app.models.organization import OrgMemberRole
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/accounts", tags=["accounts"], responses=API_ERROR_RESPONSES)


@router.get("")
def list_accounts(
    ch: ChClientDependency,
    _auth: None = Depends(require_admin_key_or_org_role(OrgMemberRole.viewer)),
) -> list[dict[str, str]]:
    rows = ch.query(
        "SELECT account_id, marketplace, organization_id, title, created_at"
        " FROM dim_account FINAL ORDER BY marketplace, title"
    )
    return [
        {
            "account_id": r[0],
            "marketplace": r[1],
            "organization_id": r[2],
            "title": r[3],
            "created_at": str(r[4]) if r[4] else "",
        }
        for r in rows.result_rows
    ]
