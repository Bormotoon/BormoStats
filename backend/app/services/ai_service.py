"""AI-powered content generation service."""

from __future__ import annotations

from typing import Any

import httpx


class AiService:
    """LLM-powered service for generating product content and review replies."""

    def __init__(self, api_url: str, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.api_url = api_url.rstrip("/") + "/chat/completions" if api_url else ""
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(timeout=60.0)

    def close(self) -> None:
        self._client.close()

    def _available(self) -> bool:
        return bool(self.api_url and self.api_key)

    def _call(self, system: str, user: str) -> str | None:
        if not self._available():
            return None
        try:
            resp = self._client.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000,
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            content: str | None = data.get("choices", [{}])[0].get("message", {}).get("content")
            return content
        except Exception:
            return None

    def generate_description(self, name: str, brand: str, category: str) -> str | None:
        """Generate an SEO-optimized product description."""
        system = "Ты — эксперт по SEO-оптимизации карточек товаров на Wildberries и Ozon."
        user = (
            f"Напиши SEO-оптимизированное описание товара на русском языке.\n"
            f"Название: {name}\nБренд: {brand}\nКатегория: {category}\n\n"
            f"Описание должно быть 3-5 предложений, содержать ключевые слова,"
            f" преимущества товара и призыв к покупке."
        )
        return self._call(system, user)

    def generate_review_reply(self, review_text: str, rating: int) -> str | None:
        """Generate a polite reply to a customer review."""
        sentiment = (
            "положительный" if rating >= 4 else "нейтральный" if rating >= 3 else "негативный"
        )
        system = (
            "Ты — вежливый и профессиональный представитель службы поддержки интернет-магазина."
        )
        user = (
            f"Напиши ответ на отзыв покупателя на русском языке.\n"
            f"Оценка: {rating} ({sentiment})\nТекст отзыва: {review_text}\n\n"
            f"Ответ должен быть вежливым, благодарить за отзыв,"
            f" и если есть проблема — предлагать её решение."
        )
        return self._call(system, user)
