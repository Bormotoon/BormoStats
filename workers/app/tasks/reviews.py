"""Buyers' reviews: collect them from WB and Ozon and auto-reply to the ones without text.

Every run stores the unanswered reviews and the recently answered ones, records the outcome
per account in ``sys_review_sync`` and then, for organizations that turned auto replies on,
answers unanswered reviews without text by the mode set for their rating (a random template
or an AI draft). Reviews with text are never answered automatically: they wait for a person
on the reviews page.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from app.utils.celery_helpers import shared_task
from app.utils.locking import LockNotAcquiredError, lock_scope
from app.utils.runtime import get_ch_client, get_redis_client, log_task_run, new_run_context

from collectors.common.http_client import CircuitOpenError
from collectors.reviews import (
    REVIEW_COLUMNS,
    OzonReviewsClient,
    WbFeedbacksClient,
    describe_error,
    parse_ozon_review,
    parse_wb_feedback,
    send_reply,
)
from common.review_store import (
    STATUS_FAILED,
    STATUS_SENT,
    auto_reply_text,
    load_settings,
    load_templates,
    record_reply,
)
from common.reviews import AiReplyClient

LOGGER = structlog.get_logger(__name__)
TASK_NAME = "tasks.reviews.sync_reviews"
WB_ACCOUNT_ID = os.getenv("WB_ACCOUNT_ID", "default")
OZON_ACCOUNT_ID = os.getenv("OZON_ACCOUNT_ID", "default")
# answered reviews are kept for the page's history this far back
ANSWERED_LOOKBACK_DAYS = 90
OZON_PROCESSED_PAGES = 10
# reviews older than this are not auto-answered: the buyer has long moved on
AUTO_REPLY_MAX_AGE_DAYS = 30
# a reply that failed is retried after this long, not on every run
FAILED_RETRY_HOURS = 6
DEFAULT_AUTO_REPLIES_PER_RUN = 100

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"
STATUS_NO_CREDENTIALS = "no_credentials"


def wb_feedbacks_token() -> str:
    """A token with the "Вопросы и отзывы" category; WB content tokens often carry it."""
    return os.getenv("WB_TOKEN_FEEDBACKS", "").strip() or os.getenv("WB_TOKEN_CONTENT", "").strip()


def auto_replies_per_run() -> int:
    try:
        return max(1, int(os.getenv("REVIEW_AUTO_REPLIES_PER_RUN", "")))
    except ValueError:
        return DEFAULT_AUTO_REPLIES_PER_RUN


def _insert_reviews(ch: Any, rows: list[dict[str, Any]]) -> None:
    if rows:
        ch.insert(
            "fct_review",
            [[r[c] for c in REVIEW_COLUMNS] for r in rows],
            column_names=REVIEW_COLUMNS,
        )


def _record_sync(
    ch: Any, marketplace: str, account_id: str, status: str, message: str, unanswered: int
) -> None:
    ch.insert(
        "sys_review_sync",
        [
            [
                marketplace,
                account_id,
                status,
                message[:1000],
                unanswered,
                datetime.now(UTC).replace(microsecond=0),
            ]
        ],
        column_names=["marketplace", "account_id", "status", "message", "unanswered", "synced_at"],
    )


def _sync_status(exc: Exception) -> str:
    """403/401/404 mean the method is not available to this key or subscription."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 404}:
        return STATUS_UNAVAILABLE
    return STATUS_ERROR


def collect_wb(ch: Any, account_id: str, now: datetime) -> tuple[str, str, int]:
    token = wb_feedbacks_token()
    if not token:
        return STATUS_NO_CREDENTIALS, "нет токена WB_TOKEN_FEEDBACKS (или WB_TOKEN_CONTENT)", 0
    with WbFeedbacksClient(token) as wb:
        unanswered = [
            parse_wb_feedback(i, account_id=account_id, synced_at=now)
            for i in wb.feedbacks(is_answered=False)
        ]
        _insert_reviews(ch, unanswered)
        answered = [
            parse_wb_feedback(i, account_id=account_id, synced_at=now)
            for i in wb.feedbacks(
                is_answered=True, date_from=now - timedelta(days=ANSWERED_LOOKBACK_DAYS)
            )
        ]
        _insert_reviews(ch, answered)
    return (
        STATUS_OK,
        f"неотвеченных {len(unanswered)},"
        f" отвеченных за {ANSWERED_LOOKBACK_DAYS} дней {len(answered)}",
        len(unanswered),
    )


def _fill_ozon_names(ch: Any, account_id: str, rows: list[dict[str, Any]]) -> None:
    """Ozon reviews name the SKU only: the article and the name come from the catalogue."""
    skus = sorted({r["product_id"] for r in rows if r["product_id"]})
    if not skus:
        return
    found = ch.query(
        "SELECT product_id, anyLast(offer_id), anyLast(title) FROM dim_product FINAL"
        " WHERE marketplace = 'ozon' AND account_id = {aid:String}"
        " AND product_id IN {skus:Array(String)} GROUP BY product_id",
        parameters={"aid": account_id, "skus": skus},
    ).result_rows
    names = {str(sku): (offer or "", title or "") for sku, offer, title in found}
    for row in rows:
        offer, title = names.get(row["product_id"], ("", ""))
        row["offer_id"], row["product_name"] = offer, title


def collect_ozon(ch: Any, account_id: str, now: datetime) -> tuple[str, str, int]:
    client_id = os.getenv("OZON_CLIENT_ID", "").strip()
    api_key = os.getenv("OZON_API_KEY", "").strip()
    if not client_id or not api_key:
        return STATUS_NO_CREDENTIALS, "нет ключа Ozon Seller API", 0
    with OzonReviewsClient(client_id, api_key) as ozon:
        unanswered = [
            parse_ozon_review(i, account_id=account_id, synced_at=now)
            for i in ozon.reviews(status="UNPROCESSED")
        ]
        processed = [
            parse_ozon_review(i, account_id=account_id, synced_at=now)
            for i in ozon.reviews(status="PROCESSED", max_pages=OZON_PROCESSED_PAGES)
        ]
    rows = unanswered + processed
    _fill_ozon_names(ch, account_id, rows)
    _insert_reviews(ch, rows)
    return (
        STATUS_OK,
        f"необработанных {len(unanswered)}, обработанных {len(processed)}",
        len(unanswered),
    )


def _account_orgs(ch: Any) -> dict[tuple[str, str], str]:
    rows = ch.query(
        "SELECT marketplace, account_id, organization_id FROM dim_account FINAL"
    ).result_rows
    return {(str(m), str(a)): str(o) for m, a, o in rows}


def pending_auto_reviews(ch: Any, organization_id: str, limit: int) -> list[dict[str, Any]]:
    """Unanswered reviews without text of the organization that no reply was sent to yet."""
    result = ch.query(
        "SELECT r.marketplace AS marketplace, r.account_id AS account_id, r.review_id AS review_id,"
        " r.rating AS rating, r.user_name AS user_name, r.product_name AS product_name"
        " FROM fct_review AS r FINAL"
        " WHERE r.is_answered = 0 AND r.has_text = 0 AND r.rating BETWEEN 1 AND 5"
        " AND r.created_at >= now() - INTERVAL {age:UInt32} DAY"
        " AND (r.marketplace, r.account_id) IN ("
        "   SELECT marketplace, account_id FROM dim_account FINAL"
        "   WHERE organization_id = {oid:String})"
        " AND (r.marketplace, r.account_id, r.review_id) NOT IN ("
        "   SELECT marketplace, account_id, review_id FROM sys_review_reply"
        "   WHERE status = {sent:String}"
        "   OR (status = {failed:String} AND created_at >= now() - INTERVAL {retry:UInt32} HOUR))"
        " ORDER BY r.created_at LIMIT {lim:UInt32}",
        parameters={
            "oid": organization_id,
            "age": AUTO_REPLY_MAX_AGE_DAYS,
            "sent": STATUS_SENT,
            "failed": STATUS_FAILED,
            "retry": FAILED_RETRY_HOURS,
            "lim": limit,
        },
    )
    return list(result.named_results())


def auto_reply(ch: Any, organization_id: str, budget: int, stats: Counter[str]) -> int:
    settings = load_settings(ch, organization_id)
    if not settings.auto_enabled or not any(settings.mode_for(r) != "off" for r in settings.modes):
        return 0
    templates = load_templates(ch, organization_id)
    sent = 0
    with AiReplyClient(
        os.getenv("AI_API_URL", ""), os.getenv("AI_API_KEY", ""), os.getenv("AI_MODEL", "")
    ) as ai:
        for review in pending_auto_reviews(ch, organization_id, budget):
            mode = settings.mode_for(int(review["rating"]))
            if mode == "off":
                continue
            text, source = auto_reply_text(review, mode, templates, ai)
            if not text:
                stats["auto_no_text"] += 1
                continue
            error = send_reply(
                review["marketplace"],
                review["review_id"],
                text,
                wb_token=wb_feedbacks_token(),
                ozon_client_id=os.getenv("OZON_CLIENT_ID", ""),
                ozon_api_key=os.getenv("OZON_API_KEY", ""),
            )
            record_reply(
                ch,
                organization_id=organization_id,
                marketplace=review["marketplace"],
                account_id=review["account_id"],
                review_id=review["review_id"],
                text=text,
                source=source,
                error=error,
                created_by="auto",
            )
            stats["auto_failed" if error else "auto_sent"] += 1
            if not error:
                sent += 1
    return sent


@shared_task(name=TASK_NAME)
def sync_reviews() -> dict[str, object]:
    """Collect reviews of every marketplace and send the auto replies that are due."""
    run_id, started_at = new_run_context()
    ch = get_ch_client()
    stats: Counter[str] = Counter()
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with lock_scope(get_redis_client(), source="reviews", account_id="all", ttl_seconds=1800):
            for marketplace, account_id, collect in (
                ("wb", WB_ACCOUNT_ID, collect_wb),
                ("ozon", OZON_ACCOUNT_ID, collect_ozon),
            ):
                try:
                    status, message, unanswered = collect(ch, account_id, now)
                except (httpx.HTTPError, CircuitOpenError) as exc:
                    status, message, unanswered = _sync_status(exc), describe_error(exc), 0
                    LOGGER.warning("reviews_collect_failed", marketplace=marketplace, error=message)
                _record_sync(ch, marketplace, account_id, status, message, unanswered)
                stats[f"{marketplace}_{status}"] += 1
                stats[f"{marketplace}_unanswered"] = unanswered

            budget = auto_replies_per_run()
            for organization_id in sorted(set(_account_orgs(ch).values())):
                if budget <= 0:
                    break
                budget -= auto_reply(ch, organization_id, budget, stats)
    except LockNotAcquiredError:
        LOGGER.warning("reviews_skipped_lock_held")
        return {"run_id": run_id, "status": "skipped"}
    except Exception as exc:
        log_task_run(ch, TASK_NAME, run_id, started_at, "failed", 0, str(exc), meta=dict(stats))
        raise
    log_task_run(
        ch,
        TASK_NAME,
        run_id,
        started_at,
        "success",
        stats["auto_sent"],
        "reviews synced",
        meta=dict(stats),
    )
    LOGGER.info("reviews_sync_complete", **stats)
    return {"run_id": run_id, "status": "success", **stats}
