from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewMode = Literal["off", "template", "ai"]
TemplateKind = Literal["no_text", "text"]
ReviewStatus = Literal["unanswered", "answered", "all"]


class Review(BaseModel):
    """A buyer's review and its reply state.

    ``is_answered`` is true once the marketplace shows an answer or BormoStats sent one;
    ``reply_*`` describe the last reply BormoStats sent or tried to send.
    """

    marketplace: str
    account_id: str
    review_id: str
    product_id: str
    offer_id: str = ""
    product_name: str = ""
    image_url: str | None = None
    rating: int
    text: str = ""
    pros: str = ""
    cons: str = ""
    has_text: bool
    user_name: str = ""
    photos: int = 0
    created_at: datetime
    is_answered: bool
    answer_text: str = ""
    reply_source: str = ""
    reply_status: str = ""
    reply_error: str = ""
    replied_at: datetime | None = None


class ReviewPage(BaseModel):
    items: list[Review]
    total: int


class ReviewSyncState(BaseModel):
    marketplace: str
    account_id: str
    status: str
    message: str = ""
    unanswered: int = 0
    synced_at: datetime | None = None


class ReviewSummary(BaseModel):
    unanswered_with_text: int
    unanswered_without_text: int
    sent_today: int
    sync: list[ReviewSyncState]
    ai_available: bool


class ReviewSettingsBody(BaseModel):
    """Auto replies to reviews without text: a master switch and a mode per rating (1..5)."""

    auto_enabled: bool = False
    modes: dict[Literal["1", "2", "3", "4", "5"], ReviewMode] = Field(default_factory=dict)


class ReviewTemplate(BaseModel):
    template_id: str
    kind: TemplateKind
    rating: int = Field(ge=1, le=5)
    text: str


class ReviewTemplateCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: TemplateKind
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=2, max_length=3000)


class ReviewTemplateUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=2, max_length=3000)


class ReplyBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=2, max_length=3000)


class DraftBody(BaseModel):
    source: Literal["ai", "template"]


class DraftResult(BaseModel):
    text: str
    source: str
