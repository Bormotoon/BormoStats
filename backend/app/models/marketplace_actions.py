from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MarketplaceAction(BaseModel):
    """Audit record of a (simulated or executed) bid/price change."""

    action_id: str
    organization_id: str
    source: str
    rule_id: str
    marketplace: str
    account_id: str
    target_type: str
    target_id: str
    before_value: float | None = None
    after_value: float
    dry_run: bool
    status: str
    response_status: int = 0
    response_body: str = ""
    idempotency_key: str
    created_at: datetime | None = None
