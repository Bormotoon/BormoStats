# ruff: noqa: E501, RUF001
# (the ready-made reply texts are kept one per line, with Russian punctuation)
"""Review replies shared by the backend and the workers: templates, text checks and AI drafts.

Templates may use the placeholders ``{имя}`` (the buyer's name as the marketplace shows it)
and ``{товар}`` (the product name); an unknown name drops the placeholder together with the
comma before it, so "Спасибо, {имя}!" becomes "Спасибо!".
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from typing import Any

import httpx

KIND_NO_TEXT = "no_text"
KIND_TEXT = "text"
KINDS = (KIND_NO_TEXT, KIND_TEXT)
MODE_OFF = "off"
MODE_TEMPLATE = "template"
MODE_AI = "ai"
MODES = (MODE_OFF, MODE_TEMPLATE, MODE_AI)
RATINGS = (1, 2, 3, 4, 5)
# WB accepts 2..5000 characters, Ozon up to 3000
MAX_REPLY_LENGTH = 3000

# the ready-made list each organization starts with; it can add, edit and delete its own
DEFAULT_TEMPLATES: dict[str, dict[int, tuple[str, ...]]] = {
    KIND_NO_TEXT: {
        5: (
            "Спасибо за высокую оценку! Рады, что покупка понравилась. Будем ждать вас снова!",
            "Благодарим за пять звёзд! Нам очень приятно. Заглядывайте к нам ещё — у нас много интересного.",
            "Спасибо, что выбрали нас и поставили отличную оценку! Хороших вам покупок.",
            "Большое спасибо за оценку! Рады были помочь. До новых встреч в нашем магазине!",
        ),
        4: (
            "Спасибо за хорошую оценку! Мы стараемся становиться лучше и будем рады видеть вас снова.",
            "Благодарим за отзыв и четыре звезды! Если что-то можно улучшить, напишите нам — нам важно ваше мнение.",
            "Спасибо, что выбрали наш товар! Рады, что он вам подошёл.",
        ),
        3: (
            "Спасибо за оценку. Нам жаль, что покупка понравилась не полностью. Расскажите, что можно улучшить, — мы учтём.",
            "Благодарим за отзыв. Будем рады узнать, чего не хватило до пяти звёзд, — это поможет нам стать лучше.",
        ),
        2: (
            "Нам очень жаль, что товар вас не порадовал. Пожалуйста, напишите, что пошло не так, — мы постараемся помочь.",
            "Спасибо, что поделились оценкой. Нам жаль, что ожидания не оправдались. Опишите проблему, и мы обязательно разберёмся.",
        ),
        1: (
            "Нам очень жаль, что покупка вас огорчила. Пожалуйста, опишите, что случилось, — мы разберёмся и поможем.",
            "Приносим извинения за неудачный опыт. Напишите нам подробнее о проблеме — мы сделаем всё, чтобы её решить.",
        ),
    },
    KIND_TEXT: {
        5: (
            "Спасибо за подробный отзыв и высокую оценку! Нам очень приятно, что товар понравился. Ждём вас снова!",
            "Благодарим за тёплые слова! Рады, что покупка оправдала ожидания. Хороших вам покупок!",
        ),
        4: (
            "Спасибо за отзыв! Рады, что товар в целом понравился. Ваши замечания обязательно учтём.",
            "Благодарим за подробную оценку! Нам важно ваше мнение — постараемся стать ещё лучше.",
        ),
        3: (
            "Спасибо за честный отзыв. Нам жаль, что не всё понравилось. Мы передали ваши замечания команде и постараемся исправиться.",
        ),
        2: (
            "Нам очень жаль, что товар вас разочаровал. Спасибо, что подробно описали проблему, — мы разберёмся. Если нужна помощь с возвратом или заменой, напишите нам.",
        ),
        1: (
            "Приносим извинения за доставленные неудобства. Мы внимательно изучим ваш отзыв и примем меры. Пожалуйста, оформите возврат через площадку — мы поможем решить вопрос.",
        ),
    },
}


def review_has_text(text: str | None, pros: str | None = None, cons: str | None = None) -> bool:
    """A review has text when any of its text fields holds a letter or a digit."""
    return any(re.search(r"\w", value or "") for value in (text, pros, cons))


def render_template(template: str, *, name: str = "", product: str = "") -> str:
    """Fill ``{имя}`` and ``{товар}``; an empty value takes the comma before it along."""
    out = template
    for key, value in (("имя", name.strip()), ("товар", product.strip())):
        if value:
            out = out.replace("{" + key + "}", value)
        else:
            out = re.sub(r",?\s*\{" + key + r"\}", "", out)
    return re.sub(r"\s+([!?.,])", r"\1", out).strip()[:MAX_REPLY_LENGTH]


def pick_template(templates: Sequence[str], rng: random.Random | None = None) -> str | None:
    """A random template of the list, so replies of the same rating do not all look alike."""
    choices = [t for t in templates if t.strip()]
    if not choices:
        return None
    return (rng or random).choice(choices)


def _sentiment(rating: int) -> str:
    return "положительный" if rating >= 4 else "нейтральный" if rating == 3 else "негативный"


def review_reply_prompt(
    *,
    rating: int,
    text: str = "",
    pros: str = "",
    cons: str = "",
    product: str = "",
    name: str = "",
) -> tuple[str, str]:
    """System and user messages asking for a reply to one review."""
    system = (
        "Ты — вежливый представитель интернет-магазина на маркетплейсе и отвечаешь покупателям на"
        " отзывы. Пиши по-русски, тепло и по делу, 2–4 предложения, без markdown, эмодзи,"
        " ссылок, телефонов и обещаний компенсаций. Не выдумывай фактов о товаре. Если в отзыве"
        " есть проблема — извинись и предложи написать в чат или оформить возврат через площадку."
    )
    parts = [f"Оценка: {rating} из 5 ({_sentiment(rating)})."]
    if product:
        parts.append(f"Товар: {product}.")
    if name:
        parts.append(f"Имя покупателя: {name}.")
    if review_has_text(text, pros, cons):
        if text:
            parts.append(f"Отзыв: {text}")
        if pros:
            parts.append(f"Достоинства: {pros}")
        if cons:
            parts.append(f"Недостатки: {cons}")
    else:
        parts.append(
            "Покупатель поставил только оценку, без текста. Ответь коротко, соответственно оценке."
        )
    parts.append("Напиши только текст ответа.")
    return system, "\n".join(parts)


class AiReplyClient:
    """An OpenAI-compatible chat completions endpoint (AI_API_URL, AI_API_KEY, AI_MODEL)."""

    def __init__(self, api_url: str, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.url = api_url.rstrip("/") + "/chat/completions" if api_url else ""
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        self._client = httpx.Client(timeout=60.0)

    @property
    def available(self) -> bool:
        return bool(self.url and self.api_key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AiReplyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def complete(self, system: str, user: str, *, max_tokens: int = 600) -> str | None:
        if not self.available:
            return None
        try:
            response = self._client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.7,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
        except httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError:
            return None
        return clean_reply(content) if isinstance(content, str) else None

    def review_reply(self, **review: Any) -> str | None:
        system, user = review_reply_prompt(**review)
        return self.complete(system, user)


def clean_reply(text: str) -> str | None:
    """Strip quotes and markdown a model may wrap a reply in; ``None`` when nothing is left."""
    out = text.strip().strip('"«»').strip()
    out = re.sub(r"[*_#`]+", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out[:MAX_REPLY_LENGTH] if len(out) >= 2 else None
