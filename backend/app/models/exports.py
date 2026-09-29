from __future__ import annotations

from datetime import date, datetime

from app.models.bidder import ACCOUNT_ID_PATTERN
from pydantic import BaseModel, Field, model_validator

from common.exports import DATASETS


class ExportRequest(BaseModel):
    dataset: str = Field(pattern="^(" + "|".join(sorted(DATASETS)) + ")$")
    marketplace: str | None = Field(default=None, pattern=r"^(wb|ozon)$")
    account_id: str | None = Field(default=None, pattern=ACCOUNT_ID_PATTERN)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> ExportRequest:
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("date_from must be on or before date_to")
            if (self.date_to - self.date_from).days > 366:
                raise ValueError("export window must not exceed 366 days")
        return self


class ExportJob(BaseModel):
    export_id: str
    organization_id: str
    requested_by: str
    dataset: str
    status: str
    row_count: int = 0
    error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
