from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

TASK_STATUS_PATTERN = r"^(open|in_progress|resolved|dismissed)$"


class ActionableTask(BaseModel):
    task_id: str
    organization_id: str = "default"
    trigger_type: str
    marketplace: str
    account_id: str
    product_id: str | None = None
    campaign_id: str | None = None
    title: str
    description: str = ""
    priority: str = "medium"
    status: str = "open"
    dedupe_key: str = ""
    created_at: datetime | None = None
    resolved_at: datetime | None = None


class TaskUpdate(BaseModel):
    status: str = Field(pattern=TASK_STATUS_PATTERN)
