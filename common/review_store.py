"""Review settings, templates and the reply log in ClickHouse, for the backend and the workers."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from common.reviews import (
    DEFAULT_TEMPLATES,
    KIND_NO_TEXT,
    KIND_TEXT,
    MODE_AI,
    MODE_OFF,
    MODE_TEMPLATE,
    MODES,
    RATINGS,
    AiReplyClient,
    pick_template,
    render_template,
)

SOURCE_AUTO_TEMPLATE = "auto_template"
SOURCE_AUTO_AI = "auto_ai"
SOURCE_MANUAL = "manual"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@dataclass
class ReviewSettings:
    auto_enabled: bool = False
    modes: dict[int, str] = field(default_factory=lambda: dict.fromkeys(RATINGS, MODE_OFF))

    def mode_for(self, rating: int) -> str:
        return self.modes.get(rating, MODE_OFF) if self.auto_enabled else MODE_OFF


@dataclass(frozen=True)
class Template:
    template_id: str
    kind: str
    rating: int
    text: str


def load_settings(ch: Any, organization_id: str) -> ReviewSettings:
    rows = ch.query(
        "SELECT auto_enabled, mode_1, mode_2, mode_3, mode_4, mode_5"
        " FROM dim_review_settings FINAL WHERE organization_id = {oid:String}",
        parameters={"oid": organization_id},
    ).result_rows
    if not rows:
        return ReviewSettings()
    auto, *modes = rows[0]
    return ReviewSettings(
        auto_enabled=bool(auto),
        modes={r: (m if m in MODES else MODE_OFF) for r, m in zip(RATINGS, modes, strict=True)},
    )


def save_settings(ch: Any, organization_id: str, settings: ReviewSettings) -> None:
    ch.insert(
        "dim_review_settings",
        [
            [
                organization_id,
                1 if settings.auto_enabled else 0,
                *(settings.modes.get(r, MODE_OFF) for r in RATINGS),
                _now(),
            ]
        ],
        column_names=[
            "organization_id",
            "auto_enabled",
            "mode_1",
            "mode_2",
            "mode_3",
            "mode_4",
            "mode_5",
            "updated_at",
        ],
    )


def default_templates() -> list[Template]:
    return [
        Template(template_id=f"default-{kind}-{rating}-{i}", kind=kind, rating=rating, text=text)
        for kind, by_rating in DEFAULT_TEMPLATES.items()
        for rating, texts in by_rating.items()
        for i, text in enumerate(texts, start=1)
    ]


def _seeded(ch: Any, organization_id: str) -> bool:
    rows = ch.query(
        "SELECT count() FROM dim_review_template WHERE organization_id = {oid:String}",
        parameters={"oid": organization_id},
    ).result_rows
    return bool(rows and rows[0][0])


def load_templates(ch: Any, organization_id: str, *, seed: bool = False) -> list[Template]:
    """The organization's templates; one that has none yet starts from the default list.

    With ``seed`` the default list is written down, so it can be edited; without it (the
    workers) the defaults are only used in memory.
    """
    if not _seeded(ch, organization_id):
        defaults = default_templates()
        if seed:
            write_templates(ch, organization_id, defaults)
        return defaults
    rows = ch.query(
        "SELECT template_id, kind, rating, text FROM dim_review_template FINAL"
        " WHERE organization_id = {oid:String} AND is_deleted = 0"
        " ORDER BY kind, rating DESC, template_id",
        parameters={"oid": organization_id},
    ).result_rows
    return [Template(str(t), str(k), int(r), str(x)) for t, k, r, x in rows]


def write_templates(
    ch: Any, organization_id: str, templates: list[Template], *, deleted: bool = False
) -> None:
    if not templates:
        return
    now = _now()
    ch.insert(
        "dim_review_template",
        [
            [organization_id, t.template_id, t.kind, t.rating, t.text, 1 if deleted else 0, now]
            for t in templates
        ],
        column_names=[
            "organization_id",
            "template_id",
            "kind",
            "rating",
            "text",
            "is_deleted",
            "updated_at",
        ],
    )


def new_template_id() -> str:
    return str(uuid.uuid4())


def templates_for(templates: list[Template], kind: str, rating: int) -> list[str]:
    return [t.text for t in templates if t.kind == kind and t.rating == rating]


def template_reply(
    templates: list[Template],
    *,
    rating: int,
    has_text: bool,
    name: str = "",
    product: str = "",
    rng: random.Random | None = None,
) -> str | None:
    """A random template of the review's rating and kind, filled in; ``None`` without any."""
    kind = KIND_TEXT if has_text else KIND_NO_TEXT
    chosen = pick_template(templates_for(templates, kind, rating), rng)
    return render_template(chosen, name=name, product=product) if chosen else None


def auto_reply_text(
    review: dict[str, Any],
    mode: str,
    templates: list[Template],
    ai: AiReplyClient | None,
) -> tuple[str | None, str]:
    """The text of an auto reply to a review without text and its source, by the rating's mode."""
    if mode == MODE_TEMPLATE:
        text = template_reply(
            templates,
            rating=int(review["rating"]),
            has_text=False,
            name=str(review.get("user_name") or ""),
            product=str(review.get("product_name") or ""),
        )
        return text, SOURCE_AUTO_TEMPLATE
    if mode == MODE_AI and ai is not None and ai.available:
        text = ai.review_reply(
            rating=int(review["rating"]),
            product=str(review.get("product_name") or ""),
            name=str(review.get("user_name") or ""),
        )
        return text, SOURCE_AUTO_AI
    return None, ""


def record_reply(
    ch: Any,
    *,
    organization_id: str,
    marketplace: str,
    account_id: str,
    review_id: str,
    text: str,
    source: str,
    error: str,
    created_by: str = "",
) -> None:
    ch.insert(
        "sys_review_reply",
        [
            [
                str(uuid.uuid4()),
                organization_id,
                marketplace,
                account_id,
                review_id,
                text,
                source,
                STATUS_FAILED if error else STATUS_SENT,
                error,
                created_by,
                _now(),
            ]
        ],
        column_names=[
            "reply_id",
            "organization_id",
            "marketplace",
            "account_id",
            "review_id",
            "text",
            "source",
            "status",
            "error",
            "created_by",
            "created_at",
        ],
    )
