from __future__ import annotations

from typing import Any

import httpx

from automation.actions.telegram import TelegramAction


def test_telegram_action_sends_message(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
            calls.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    action = TelegramAction(bot_token="bot-token", chat_id="chat-id")
    action.execute(rule_name="low_stock", payload={"sku": "X1"}, message="Stock is low")

    assert len(calls) == 1
    url, body = calls[0]
    assert url == "https://api.telegram.org/botbot-token/sendMessage"
    assert body["chat_id"] == "chat-id"
    assert body["text"] == "[low_stock] Stock is low"
