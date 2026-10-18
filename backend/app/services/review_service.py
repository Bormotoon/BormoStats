"""Reviews of one organization: the list, replies, drafts, auto-reply settings and templates."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.db.ch import query_dicts
from app.models.reviews import (
    DraftResult,
    Review,
    ReviewPage,
    ReviewSettingsBody,
    ReviewSummary,
    ReviewSyncState,
    ReviewTemplate,
    ReviewTemplateCreate,
)
from app.services.tenancy import account_scope_sql
from clickhouse_connect.driver import Client

from collectors.reviews import send_reply
from common.review_store import (
    SOURCE_MANUAL,
    ReviewSettings,
    Template,
    load_settings,
    load_templates,
    new_template_id,
    record_reply,
    save_settings,
    template_reply,
    write_templates,
)
from common.reviews import RATINGS, AiReplyClient

# the last reply BormoStats sent or tried per review, and whether any was sent
_REPLIES = (
    "SELECT marketplace, account_id, review_id,"
    " argMax(text, created_at) AS last_text, argMax(source, created_at) AS last_source,"
    " argMax(status, created_at) AS last_status, argMax(error, created_at) AS last_error,"
    " max(created_at) AS last_at, countIf(status = 'sent') > 0 AS any_sent,"
    " argMaxIf(text, created_at, status = 'sent') AS sent_text"
    " FROM sys_review_reply WHERE organization_id = {oid:String}"
    " GROUP BY marketplace, account_id, review_id"
)
_IMAGES = (
    "SELECT marketplace, account_id, product_id, anyLast(image_url) AS image"
    " FROM dim_product FINAL WHERE image_url IS NOT NULL"
    " GROUP BY marketplace, account_id, product_id"
)
_FROM = (
    " FROM fct_review AS r FINAL"
    f" LEFT JOIN ({_REPLIES}) AS p"
    " ON p.marketplace = r.marketplace AND p.account_id = r.account_id"
    " AND p.review_id = r.review_id"
    f" LEFT JOIN ({_IMAGES}) AS i"
    " ON i.marketplace = r.marketplace AND i.account_id = r.account_id"
    " AND i.product_id = r.product_id"
)
_ANSWERED = "(r.is_answered = 1 OR p.any_sent = 1)"
_COLS = (
    "r.marketplace AS marketplace, r.account_id AS account_id, r.review_id AS review_id,"
    " r.product_id AS product_id, r.offer_id AS offer_id, r.product_name AS product_name,"
    " i.image AS image_url, r.rating AS rating, r.text AS text, r.pros AS pros, r.cons AS cons,"
    " r.has_text AS has_text, r.user_name AS user_name, r.photos AS photos,"
    f" r.created_at AS created_at, {_ANSWERED} AS answered,"
    " if(r.answer_text != '', r.answer_text, p.sent_text) AS answer_text,"
    " p.last_source AS reply_source, p.last_status AS reply_status,"
    " p.last_error AS reply_error, p.last_at AS replied_at"
)
# LEFT JOIN without join_use_nulls fills a missing reply with the epoch
_EPOCH_YEAR = 1970


class ReviewNotFoundError(LookupError):
    pass


class ReplyFailedError(RuntimeError):
    pass


class AiUnavailableError(RuntimeError):
    pass


class ReviewService:
    def __init__(self, ch: Client, organization_id: str, settings: Settings) -> None:
        self._ch = ch
        self._org = organization_id
        self._settings = settings

    # -- list --

    def _where(
        self,
        *,
        marketplace: str | None,
        status: str,
        has_text: bool | None,
        rating: int | None,
        query: str | None,
    ) -> tuple[str, dict[str, object]]:
        where = [account_scope_sql("oid", alias="r")]
        params: dict[str, object] = {"oid": self._org}
        if marketplace:
            where.append("r.marketplace = {mp:String}")
            params["mp"] = marketplace
        if status == "unanswered":
            where.append(f"NOT {_ANSWERED}")
        elif status == "answered":
            where.append(_ANSWERED)
        if has_text is not None:
            where.append("r.has_text = {ht:UInt8}")
            params["ht"] = 1 if has_text else 0
        if rating:
            where.append("r.rating = {rating:UInt8}")
            params["rating"] = rating
        if query:
            where.append(
                "(positionCaseInsensitiveUTF8(r.offer_id, {q:String}) > 0"
                " OR positionCaseInsensitiveUTF8(r.product_name, {q:String}) > 0"
                " OR positionCaseInsensitiveUTF8(r.text, {q:String}) > 0)"
            )
            params["q"] = query
        return " WHERE " + " AND ".join(where), params

    def list_reviews(
        self,
        *,
        marketplace: str | None = None,
        status: str = "unanswered",
        has_text: bool | None = None,
        rating: int | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewPage:
        clause, params = self._where(
            marketplace=marketplace, status=status, has_text=has_text, rating=rating, query=query
        )
        rows = query_dicts(
            self._ch,
            f"SELECT {_COLS}{_FROM}{clause}"
            " ORDER BY r.created_at DESC LIMIT {lim:UInt32} OFFSET {off:UInt32}",
            {**params, "lim": limit, "off": offset},
        )
        total = self._ch.query(f"SELECT count(){_FROM}{clause}", parameters=params).result_rows
        return ReviewPage(items=[_review(r) for r in rows], total=int(total[0][0]) if total else 0)

    def get_review(self, marketplace: str, review_id: str) -> Review:
        clause, params = self._where(
            marketplace=marketplace, status="all", has_text=None, rating=None, query=None
        )
        rows = query_dicts(
            self._ch,
            f"SELECT {_COLS}{_FROM}{clause} AND r.review_id = {{rid:String}} LIMIT 1",
            {**params, "rid": review_id},
        )
        if not rows:
            raise ReviewNotFoundError(review_id)
        return _review(rows[0])

    def summary(self) -> ReviewSummary:
        clause, params = self._where(
            marketplace=None, status="unanswered", has_text=None, rating=None, query=None
        )
        counts = self._ch.query(
            f"SELECT countIf(r.has_text = 1), countIf(r.has_text = 0){_FROM}{clause}",
            parameters=params,
        ).result_rows
        sent = self._ch.query(
            "SELECT count() FROM sys_review_reply WHERE organization_id = {oid:String}"
            " AND status = 'sent' AND created_at >= toStartOfDay(now('Europe/Moscow'))",
            parameters={"oid": self._org},
        ).result_rows
        sync = query_dicts(
            self._ch,
            "SELECT marketplace, account_id, status, message, unanswered, synced_at"
            f" FROM sys_review_sync FINAL WHERE {account_scope_sql('oid')}"
            " ORDER BY marketplace, account_id",
            {"oid": self._org},
        )
        with_text, without_text = counts[0] if counts else (0, 0)
        return ReviewSummary(
            unanswered_with_text=int(with_text),
            unanswered_without_text=int(without_text),
            sent_today=int(sent[0][0]) if sent else 0,
            sync=[ReviewSyncState(**r) for r in sync],
            ai_available=self._ai().available,
        )

    # -- replies --

    def _ai(self) -> AiReplyClient:
        s = self._settings
        return AiReplyClient(s.ai_api_url, s.ai_api_key, s.ai_model)

    def reply(self, marketplace: str, review_id: str, text: str, author: str) -> Review:
        review = self.get_review(marketplace, review_id)
        s = self._settings
        error = send_reply(
            marketplace,
            review_id,
            text,
            wb_token=s.wb_feedbacks_token or s.wb_content_token,
            ozon_client_id=s.ozon_client_id,
            ozon_api_key=s.ozon_api_key,
        )
        record_reply(
            self._ch,
            organization_id=self._org,
            marketplace=marketplace,
            account_id=review.account_id,
            review_id=review_id,
            text=text,
            source=SOURCE_MANUAL,
            error=error,
            created_by=author,
        )
        if error:
            raise ReplyFailedError(error)
        return self.get_review(marketplace, review_id)

    def draft(self, marketplace: str, review_id: str, source: str) -> DraftResult:
        review = self.get_review(marketplace, review_id)
        if source == "template":
            text = template_reply(
                load_templates(self._ch, self._org, seed=True),
                rating=review.rating,
                has_text=review.has_text,
                name=review.user_name,
                product=review.product_name,
            )
            return DraftResult(text=text or "", source="template")
        with self._ai() as ai:
            if not ai.available:
                raise AiUnavailableError("AI_API_URL and AI_API_KEY are not set")
            text = ai.review_reply(
                rating=review.rating,
                text=review.text,
                pros=review.pros,
                cons=review.cons,
                product=review.product_name,
                name=review.user_name,
            )
        if not text:
            raise AiUnavailableError("the AI service did not answer")
        return DraftResult(text=text, source="ai")

    # -- settings and templates --

    def get_settings(self) -> ReviewSettingsBody:
        s = load_settings(self._ch, self._org)
        return ReviewSettingsBody.model_validate(
            {
                "auto_enabled": s.auto_enabled,
                "modes": {str(r): s.modes.get(r, "off") for r in RATINGS},
            }
        )

    def save_settings(self, body: ReviewSettingsBody) -> ReviewSettingsBody:
        current = load_settings(self._ch, self._org)
        modes = {**current.modes, **{int(k): v for k, v in body.modes.items()}}
        save_settings(
            self._ch, self._org, ReviewSettings(auto_enabled=body.auto_enabled, modes=modes)
        )
        return self.get_settings()

    def list_templates(self) -> list[ReviewTemplate]:
        return [_template_out(t) for t in load_templates(self._ch, self._org, seed=True)]

    def create_template(self, body: ReviewTemplateCreate) -> ReviewTemplate:
        load_templates(self._ch, self._org, seed=True)
        template = Template(new_template_id(), body.kind, body.rating, body.text)
        write_templates(self._ch, self._org, [template])
        return ReviewTemplate(
            template_id=template.template_id, kind=body.kind, rating=body.rating, text=body.text
        )

    def _template(self, template_id: str) -> Template | None:
        return next(
            (
                t
                for t in load_templates(self._ch, self._org, seed=True)
                if t.template_id == template_id
            ),
            None,
        )

    def update_template(self, template_id: str, text: str) -> ReviewTemplate | None:
        found = self._template(template_id)
        if found is None:
            return None
        updated = Template(found.template_id, found.kind, found.rating, text)
        write_templates(self._ch, self._org, [updated])
        return _template_out(updated)

    def delete_template(self, template_id: str) -> bool:
        found = self._template(template_id)
        if found is None:
            return False
        write_templates(self._ch, self._org, [found], deleted=True)
        return True


def _template_out(t: Template) -> ReviewTemplate:
    return ReviewTemplate.model_validate(asdict(t))


def _when(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) and value.year > _EPOCH_YEAR else None


def _review(r: dict[str, Any]) -> Review:
    return Review(
        marketplace=r["marketplace"],
        account_id=r["account_id"],
        review_id=r["review_id"],
        product_id=r["product_id"],
        offer_id=r.get("offer_id") or "",
        product_name=r.get("product_name") or "",
        image_url=r.get("image_url") or None,
        rating=int(r["rating"]),
        text=r.get("text") or "",
        pros=r.get("pros") or "",
        cons=r.get("cons") or "",
        has_text=bool(r["has_text"]),
        user_name=r.get("user_name") or "",
        photos=int(r.get("photos") or 0),
        created_at=r["created_at"],
        is_answered=bool(r["answered"]),
        answer_text=r.get("answer_text") or "",
        reply_source=r.get("reply_source") or "",
        reply_status=r.get("reply_status") or "",
        reply_error=r.get("reply_error") or "",
        replied_at=_when(r.get("replied_at")),
    )
