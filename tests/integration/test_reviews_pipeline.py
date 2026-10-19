"""Reviews end to end: collection, auto replies to ratings without text, manual replies,
templates; plus desired prices imported from a spreadsheet and the shop name."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from app.services import review_service
from app.tasks import reviews as reviews_task

ACCOUNT = "default"


def _feedback(fid: str, rating: int, *, text: str = "", hours_ago: int = 1) -> dict[str, Any]:
    created = datetime.now(UTC) - timedelta(hours=hours_ago)
    return {
        "id": fid,
        "text": text,
        "pros": "",
        "cons": "",
        "productValuation": rating,
        "createdDate": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "answer": None,
        "productDetails": {"nmId": 1001, "supplierArticle": "btn1", "productName": "Пуговицы"},
        "userName": "Анна",
    }


class _FakeWb:
    unanswered: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, token: str) -> None:
        assert token == "feedbacks-token"

    def __enter__(self) -> _FakeWb:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def feedbacks(self, *, is_answered: bool, date_from: datetime | None = None) -> Iterator[Any]:
        yield from ([] if is_answered else self.unanswered)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []

    def fake_send(marketplace: str, review_id: str, text: str, **_: Any) -> str:
        calls.append((marketplace, review_id, text))
        return "HTTP 400: too short" if review_id == "bad" else ""

    monkeypatch.setenv("WB_TOKEN_FEEDBACKS", "feedbacks-token")
    monkeypatch.delenv("OZON_CLIENT_ID", raising=False)
    monkeypatch.delenv("AI_API_URL", raising=False)
    monkeypatch.setattr(reviews_task, "WbFeedbacksClient", _FakeWb)
    monkeypatch.setattr(reviews_task, "send_reply", fake_send)
    monkeypatch.setattr(review_service, "send_reply", fake_send)
    return calls


def test_reviews_sync_auto_and_manual_replies(
    integration_runtime: Any, api_client: Any, sent: list[tuple[str, str, str]]
) -> None:
    client = integration_runtime.ch_client()
    try:
        _FakeWb.unanswered = [
            _feedback("five", 5),
            _feedback("one", 1),
            _feedback("text", 5, text="Отличные пуговицы"),
            _feedback("old", 5, hours_ago=24 * 40),
        ]
        assert reviews_task.sync_reviews()["status"] == "success"
        # auto replies are off by default: nothing is sent
        assert sent == []
        summary = api_client.get("/api/v1/reviews/summary").json()
        assert (summary["unanswered_with_text"], summary["unanswered_without_text"]) == (1, 3)
        sync = {s["marketplace"]: s["status"] for s in summary["sync"]}
        assert sync == {"wb": "ok", "ozon": "no_credentials"}

        # the ready-made templates are written down on the first read
        templates = api_client.get("/api/v1/reviews/templates").json()
        five_star = [t for t in templates if t["kind"] == "no_text" and t["rating"] == 5]
        assert len(five_star) >= 3
        for t in five_star:
            assert api_client.delete(f"/api/v1/reviews/templates/{t['template_id']}").is_success
        created = api_client.post(
            "/api/v1/reviews/templates",
            json={"kind": "no_text", "rating": 5, "text": "Спасибо, {имя}!"},
        )
        assert created.status_code == 201, created.text

        settings = api_client.put(
            "/api/v1/reviews/settings",
            json={"auto_enabled": True, "modes": {"5": "template", "1": "ai"}},
        )
        assert settings.json()["modes"] == {
            "1": "ai",
            "2": "off",
            "3": "off",
            "4": "off",
            "5": "template",
        }
        result = reviews_task.sync_reviews()
        # 5 stars: the template; 1 star: AI is not configured, so it waits; the review with
        # text and the 40-day-old one are never auto-answered
        assert sent == [("wb", "five", "Спасибо, Анна!")]
        assert result["auto_sent"] == 1
        reviews_task.sync_reviews()
        assert len(sent) == 1  # a review is answered once

        answered = api_client.get("/api/v1/reviews", params={"status": "answered"}).json()
        assert [(r["review_id"], r["reply_source"]) for r in answered["items"]] == [
            ("five", "auto_template")
        ]
        assert answered["items"][0]["answer_text"] == "Спасибо, Анна!"

        waiting = api_client.get("/api/v1/reviews", params={"has_text": "true"}).json()
        assert [r["review_id"] for r in waiting["items"]] == ["text"]
        draft = api_client.post("/api/v1/reviews/wb/text/draft", json={"source": "template"})
        assert draft.status_code == 200 and draft.json()["text"]
        ai = api_client.post("/api/v1/reviews/wb/text/draft", json={"source": "ai"})
        assert ai.status_code == 503
        reply = api_client.post("/api/v1/reviews/wb/text/reply", json={"text": "Спасибо за отзыв!"})
        assert reply.status_code == 200, reply.text
        assert reply.json()["is_answered"] is True and reply.json()["reply_source"] == "manual"
        assert (
            api_client.post("/api/v1/reviews/wb/nope/reply", json={"text": "Привет"}).status_code
            == 404
        )
        summary = api_client.get("/api/v1/reviews/summary").json()
        assert summary["unanswered_with_text"] == 0 and summary["sent_today"] == 2
    finally:
        client.close()


def test_desired_prices_import_and_keep(integration_runtime: Any, api_client: Any) -> None:
    client = integration_runtime.ch_client()
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        client.insert(
            "mrt_price_current",
            [
                ["wb", ACCOUNT, offer, pid, 1000.0, 50.0, 500.0, 0.0, 0.0, 0.0, 0.0, 0.0, now, now]
                for offer, pid in (("btn1", "1001"), ("btn2", "1002"))
            ],
            column_names=[
                "marketplace",
                "account_id",
                "offer_id",
                "product_id",
                "list_price",
                "seller_discount_pct",
                "seller_price",
                "commission_pct",
                "commission_rub",
                "acquiring_rub",
                "logistics_rub",
                "fees_rub",
                "price_seen_at",
                "built_at",
            ],
        )
        text = "Артикул продавца\tЖелаемая цена для МП (WB)\nbtn1\t450\nbtn2\t\nghost\t300\n"
        result = api_client.post(
            "/api/v1/pricing/targets/import", json={"marketplace": "wb", "text": text}
        )
        assert result.status_code == 200, result.text
        assert result.json() == {
            "imported": 1,
            "errors": [],
            "not_found": ["ghost"],
            "updated": ["btn1"],
        }
        again = api_client.post(
            "/api/v1/pricing/targets/import", json={"marketplace": "wb", "text": "btn1;460"}
        )
        assert again.json()["imported"] == 1
        rules = api_client.get("/api/v1/repricer/rules", params={"marketplace": "wb"}).json()
        assert [(r["product_id"], r["target_price"], r["dry_run"], r["mode"]) for r in rules] == [
            ("btn1", 460.0, True, "buyer_price")
        ]
        kept = api_client.post(
            "/api/v1/pricing/targets/keep", json={"marketplace": "wb", "keep": True}
        )
        assert kept.status_code == 200, kept.text
        assert kept.json()["rules"] == 1
        rules = api_client.get("/api/v1/repricer/rules", params={"marketplace": "wb"}).json()
        assert [r["dry_run"] for r in rules] == [False]
        assert api_client.get("/api/v1/pricing/status").json() == {
            "marketplace_actions_enabled": False
        }
    finally:
        client.close()


def test_shop_name_is_in_the_principal(integration_runtime: Any, api_client: Any) -> None:
    before = api_client.get("/api/v1/users/me").json()["organization_name"]
    try:
        renamed = api_client.put("/api/v1/users/me/organization", json={"name": "  A-Lux Fashion "})
        assert renamed.status_code == 200, renamed.text
        assert api_client.get("/api/v1/users/me").json()["organization_name"] == "A-Lux Fashion"
        assert (
            api_client.put("/api/v1/users/me/organization", json={"name": "  "}).status_code == 422
        )
    finally:
        api_client.put("/api/v1/users/me/organization", json={"name": before})
