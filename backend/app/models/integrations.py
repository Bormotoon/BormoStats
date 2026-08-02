from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StockUpdateItem(BaseModel):
    sku: str
    stock: int = Field(ge=0)
    warehouse_id: int | None = Field(default=None, description="WB warehouse ID, required for WB")


class StockUpdateRequest(BaseModel):
    items: list[StockUpdateItem]
    marketplace: str | None = Field(
        default=None, description="'wb' or 'ozon' — if None, push to both"
    )


class StockUpdateResult(BaseModel):
    marketplace: str
    success: bool
    errors: list[str] = []


class WebhookSubscription(BaseModel):
    subscription_id: str
    organization_id: str = "default"
    name: str
    endpoint_url: str
    secret: str = ""
    events: list[str] = []
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WebhookSubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    endpoint_url: str = Field(min_length=1)
    secret: str = ""
    events: list[str] = []


class WebhookSubscriptionUpdate(BaseModel):
    name: str | None = None
    endpoint_url: str | None = None
    secret: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None


class WebhookLog(BaseModel):
    log_id: str
    organization_id: str = "default"
    subscription_id: str | None = None
    event_type: str
    request_body: str = ""
    response_body: str = ""
    response_status: int = 0
    success: bool = False
    created_at: datetime | None = None
