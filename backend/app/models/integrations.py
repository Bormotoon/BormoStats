from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

MAX_STOCK_UPDATE_ITEMS = 1000


class StockUpdateItem(BaseModel):
    sku: str = Field(min_length=1, max_length=128)
    stock: int = Field(ge=0, le=1_000_000)
    warehouse_id: int | None = Field(default=None, description="Warehouse ID, required")


class StockUpdateResult(BaseModel):
    marketplace: str
    success: bool
    errors: list[str] = Field(default_factory=list)


class WebhookSubscription(BaseModel):
    """Subscription as returned by the API; the signing secret is never included."""

    subscription_id: str
    organization_id: str = "default"
    name: str
    endpoint_url: str
    events: list[str] = Field(default_factory=list)
    is_active: bool = True
    has_secret: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WebhookSubscriptionWithSecret(WebhookSubscription):
    """Returned once on create/rotate so the receiver can verify signatures."""

    secret: str


class WebhookSubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    endpoint_url: str = Field(min_length=8, max_length=2048)
    events: list[str] = Field(min_length=1, max_length=20)


class WebhookSubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint_url: str | None = Field(default=None, min_length=8, max_length=2048)
    events: list[str] | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None


class WebhookTestResult(BaseModel):
    event_id: str
    queued: bool


class WebhookLog(BaseModel):
    log_id: str
    organization_id: str = "default"
    subscription_id: str | None = None
    event_id: str = ""
    event_type: str
    attempt: int = 1
    status: str = ""
    request_body: str = ""
    response_body: str = ""
    response_status: int = 0
    success: bool = False
    duration_ms: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime | None = None
