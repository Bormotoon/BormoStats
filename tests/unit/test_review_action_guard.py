from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1 import reviews as review_routes
from app.services import review_service

from tests.fakes import FakeClickHouse


def test_manual_review_reply_is_audited_but_not_sent_when_actions_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ch = FakeClickHouse()
    settings = SimpleNamespace(
        marketplace_actions_enabled=False,
        ym_account_id="default",
        ym_campaign_id="",
        wb_feedbacks_token="",
        wb_content_token="",
        ozon_client_id="",
        ozon_api_key="",
        ym_api_key_reviews="",
        ym_api_key="",
        ym_business_id="",
    )
    service = review_service.ReviewService(ch, "org", settings)
    review = SimpleNamespace(account_id="default")
    sent: list[str] = []
    monkeypatch.setenv("MARKETPLACE_ACTIONS_ENABLED", "false")
    monkeypatch.setattr(service, "get_review", lambda *_: review)
    monkeypatch.setattr(review_service, "send_reply", lambda *args, **kwargs: sent.append("sent"))
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        review_service,
        "record_reply",
        lambda _ch, **kwargs: recorded.append(kwargs),
    )

    with pytest.raises(review_service.ReplyFailedError, match="disabled"):
        service.reply("ym", "review-1", "reply", "operator")

    assert sent == []
    assert recorded[0]["error"] == "Marketplace actions are disabled"


def test_reply_route_requires_marketplace_execute_scope() -> None:
    dependency = review_routes.reply_to_review.__annotations__["auth"]
    assert "MarketplaceExecuteAuth" in str(dependency)
