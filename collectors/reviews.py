"""Buyers' reviews: WB Feedbacks API and Ozon Review API (read and reply).

WB: https://feedbacks-api.wildberries.ru, a token with the "Вопросы и отзывы" category; every
method of the category shares 3 requests per second. Ozon: the Review API of the Seller API,
available to sellers with the Premium Plus subscription (403 otherwise).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from collectors.common.http_client import JsonHttpClient
from common.reviews import review_has_text

WB_FEEDBACKS_BASE_URL = "https://feedbacks-api.wildberries.ru"
WB_FEEDBACKS_PATH = "/api/v1/feedbacks"
WB_FEEDBACK_ANSWER_PATH = "/api/v1/feedbacks/answer"
WB_FEEDBACKS_PAGE = 5000
WB_FEEDBACKS_MAX_SKIP = 199_990
# 3 requests per second for the whole category
WB_FEEDBACKS_PAUSE_SECONDS = 0.35

OZON_BASE_URL = "https://api-seller.ozon.ru"
OZON_REVIEW_LIST_PATH = "/v1/review/list"
OZON_REVIEW_COMMENT_PATH = "/v1/review/comment/create"
OZON_REVIEW_PAGE = 100
OZON_REVIEW_MAX_PAGES = 200


def _ts(value: Any) -> datetime:
    """An ISO timestamp of the API as an aware UTC datetime (now when missing)."""
    if isinstance(value, str) and value:
        with suppress(ValueError):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
    return datetime.now(UTC)


class WbFeedbacksClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._http = JsonHttpClient(WB_FEEDBACKS_BASE_URL, marketplace="wb")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WbFeedbacksClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._token}

    def feedbacks(
        self, *, is_answered: bool, date_from: datetime | None = None, max_items: int = 50_000
    ) -> Iterator[dict[str, Any]]:
        """Feedbacks, newest first, page by page; ``date_from`` bounds answered ones."""
        skip = 0
        returned = 0
        while skip <= WB_FEEDBACKS_MAX_SKIP and returned < max_items:
            params: dict[str, Any] = {
                "isAnswered": str(is_answered).lower(),
                "take": WB_FEEDBACKS_PAGE,
                "skip": skip,
                "order": "dateDesc",
            }
            if date_from is not None:
                params["dateFrom"] = int(date_from.timestamp())
            payload = self._http.get(WB_FEEDBACKS_PATH, headers=self._headers(), params=params)
            data = payload.get("data") if isinstance(payload, dict) else None
            items = [i for i in (data or {}).get("feedbacks") or [] if isinstance(i, dict)]
            yield from items
            returned += len(items)
            if len(items) < WB_FEEDBACKS_PAGE:
                return
            skip += WB_FEEDBACKS_PAGE
            time.sleep(WB_FEEDBACKS_PAUSE_SECONDS)

    def answer(self, feedback_id: str, text: str) -> None:
        self._http.post(
            WB_FEEDBACK_ANSWER_PATH, headers=self._headers(), json={"id": feedback_id, "text": text}
        )
        time.sleep(WB_FEEDBACKS_PAUSE_SECONDS)


class OzonReviewsClient:
    def __init__(self, client_id: str, api_key: str) -> None:
        self._client_id = client_id
        self._api_key = api_key
        self._http = JsonHttpClient(OZON_BASE_URL, marketplace="ozon")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OzonReviewsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Client-Id": self._client_id, "Api-Key": self._api_key}

    def reviews(
        self, *, status: str, max_pages: int = OZON_REVIEW_MAX_PAGES
    ) -> Iterator[dict[str, Any]]:
        """Reviews of a status (UNPROCESSED, PROCESSED or ALL), newest first."""
        last_id = ""
        for _ in range(max_pages):
            body: dict[str, Any] = {"limit": OZON_REVIEW_PAGE, "sort_dir": "DESC", "status": status}
            if last_id:
                body["last_id"] = last_id
            payload = self._http.post(OZON_REVIEW_LIST_PATH, headers=self._headers(), json=body)
            payload = payload if isinstance(payload, dict) else {}
            yield from (r for r in payload.get("reviews") or [] if isinstance(r, dict))
            last_id = str(payload.get("last_id") or "")
            if not payload.get("has_next") or not last_id:
                return

    def comment(self, review_id: str, text: str) -> None:
        self._http.post(
            OZON_REVIEW_COMMENT_PATH,
            headers=self._headers(),
            json={"review_id": review_id, "text": text, "mark_review_as_processed": True},
        )


def parse_wb_feedback(
    item: dict[str, Any], *, account_id: str, synced_at: datetime
) -> dict[str, Any]:
    details = item.get("productDetails") or {}
    answer = item.get("answer") or {}
    text = str(item.get("text") or "")
    pros = str(item.get("pros") or "")
    cons = str(item.get("cons") or "")
    answer_text = str(answer.get("text") or "") if isinstance(answer, dict) else ""
    return {
        "marketplace": "wb",
        "account_id": account_id,
        "review_id": str(item.get("id") or ""),
        "product_id": str(details.get("nmId") or ""),
        "offer_id": str(details.get("supplierArticle") or ""),
        "product_name": str(details.get("productName") or ""),
        "rating": int(item.get("productValuation") or 0),
        "text": text,
        "pros": pros,
        "cons": cons,
        "has_text": 1 if review_has_text(text, pros, cons) else 0,
        "user_name": str(item.get("userName") or ""),
        "photos": len(item.get("photoLinks") or []),
        "created_at": _ts(item.get("createdDate")),
        "is_answered": 1 if answer_text else 0,
        "answer_text": answer_text,
        "payload": json.dumps(item, ensure_ascii=False)[:20_000],
        "synced_at": synced_at,
    }


def parse_ozon_review(
    item: dict[str, Any], *, account_id: str, synced_at: datetime
) -> dict[str, Any]:
    text = str(item.get("text") or "")
    return {
        "marketplace": "ozon",
        "account_id": account_id,
        "review_id": str(item.get("id") or ""),
        "product_id": str(item.get("sku") or ""),
        "offer_id": "",
        "product_name": "",
        "rating": int(item.get("rating") or 0),
        "text": text,
        "pros": "",
        "cons": "",
        "has_text": 1 if review_has_text(text) else 0,
        "user_name": "",
        "photos": int(item.get("photos_amount") or 0),
        "created_at": _ts(item.get("published_at")),
        # Ozon marks a review PROCESSED once it is answered (or marked by hand)
        "is_answered": 1
        if item.get("status") == "PROCESSED" or int(item.get("comments_amount") or 0) > 0
        else 0,
        "answer_text": "",
        "payload": json.dumps(item, ensure_ascii=False)[:20_000],
        "synced_at": synced_at,
    }


REVIEW_COLUMNS = [
    "marketplace",
    "account_id",
    "review_id",
    "product_id",
    "offer_id",
    "product_name",
    "rating",
    "text",
    "pros",
    "cons",
    "has_text",
    "user_name",
    "photos",
    "created_at",
    "is_answered",
    "answer_text",
    "payload",
    "synced_at",
]


def send_reply(
    marketplace: str,
    review_id: str,
    text: str,
    *,
    wb_token: str = "",
    ozon_client_id: str = "",
    ozon_api_key: str = "",
) -> str:
    """Send one reply; returns "" on success or the error to show and keep."""
    try:
        if marketplace == "wb":
            if not wb_token:
                return "нет токена WB с категорией «Вопросы и отзывы» (WB_TOKEN_FEEDBACKS)"
            with WbFeedbacksClient(wb_token) as wb:
                wb.answer(review_id, text)
        elif marketplace == "ozon":
            if not (ozon_client_id and ozon_api_key):
                return "нет ключа Ozon Seller API (OZON_CLIENT_ID, OZON_API_KEY)"
            with OzonReviewsClient(ozon_client_id, ozon_api_key) as ozon:
                ozon.comment(review_id, text)
        else:
            return f"площадка {marketplace} не поддерживается"
    except Exception as exc:
        return describe_error(exc)
    return ""


def describe_error(exc: Exception) -> str:
    """An HTTP error as "HTTP 403: <body>", trimmed for storage and display."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}: {response.text[:500]}"
    return f"{type(exc).__name__}: {exc}"[:500]
