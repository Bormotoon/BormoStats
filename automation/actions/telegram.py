"""Telegram action implementation."""

from __future__ import annotations

from typing import Any

import httpx


class TelegramAction:
    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: float = 10.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def execute(self, rule_name: str, payload: dict[str, Any], message: str) -> None:
        if not self.enabled:
            return

        body = {
            "chat_id": self.chat_id,
            "text": f"[{rule_name}] {message}",
            "disable_web_page_preview": True,
        }
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, json=body)
            response.raise_for_status()
