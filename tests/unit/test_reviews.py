from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from app.services.pricing_service import parse_article_table

from collectors.reviews import parse_ozon_review, parse_wb_feedback
from common.review_store import (
    SOURCE_AUTO_AI,
    SOURCE_AUTO_TEMPLATE,
    ReviewSettings,
    Template,
    auto_reply_text,
    default_templates,
    template_reply,
)
from common.reviews import (
    DEFAULT_TEMPLATES,
    KIND_NO_TEXT,
    KIND_TEXT,
    RATINGS,
    clean_reply,
    render_template,
    review_has_text,
    review_reply_prompt,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "pros", "cons", "expected"),
    [
        ("", "", "", False),
        ("   ", None, "\n", False),
        ("👍", "", "", False),
        ("", "Качество", "", True),
        ("Отлично", "", "", True),
        ("", "", "5", True),
    ],
)
def test_review_has_text(text: str, pros: str | None, cons: str, expected: bool) -> None:
    assert review_has_text(text, pros, cons) is expected


def test_render_template_fills_or_drops_placeholders() -> None:
    template = "Спасибо, {имя}! Рады, что {товар} понравился."
    assert render_template(template, name="Анна", product="набор") == (
        "Спасибо, Анна! Рады, что набор понравился."
    )
    assert render_template(template) == "Спасибо! Рады, что понравился."


def test_default_templates_cover_every_rating_and_kind() -> None:
    for kind in (KIND_NO_TEXT, KIND_TEXT):
        assert set(DEFAULT_TEMPLATES[kind]) == set(RATINGS)
    ids = [t.template_id for t in default_templates()]
    assert len(ids) == len(set(ids))


def test_template_reply_picks_the_rating_and_kind() -> None:
    templates = [
        Template("a", KIND_NO_TEXT, 5, "Спасибо за пять звёзд, {имя}!"),
        Template("b", KIND_NO_TEXT, 1, "Нам жаль."),
        Template("c", KIND_TEXT, 5, "Спасибо за отзыв."),
    ]
    rng = random.Random(1)
    assert template_reply(templates, rating=5, has_text=False, name="Олег", rng=rng) == (
        "Спасибо за пять звёзд, Олег!"
    )
    assert template_reply(templates, rating=5, has_text=True) == "Спасибо за отзыв."
    assert template_reply(templates, rating=3, has_text=False) is None


class _FakeAi:
    available = True

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def review_reply(self, **review: object) -> str:
        self.calls.append(review)
        return "Спасибо за оценку!"


def test_auto_reply_text_by_mode() -> None:
    review = {"rating": 4, "user_name": "", "product_name": "Пуговицы"}
    templates = [Template("a", KIND_NO_TEXT, 4, "Спасибо!")]
    ai = _FakeAi()
    assert auto_reply_text(review, "template", templates, ai) == ("Спасибо!", SOURCE_AUTO_TEMPLATE)  # type: ignore[arg-type]
    assert auto_reply_text(review, "ai", templates, ai) == ("Спасибо за оценку!", SOURCE_AUTO_AI)  # type: ignore[arg-type]
    assert ai.calls == [{"rating": 4, "product": "Пуговицы", "name": ""}]
    assert auto_reply_text(review, "off", templates, ai) == (None, "")  # type: ignore[arg-type]
    assert auto_reply_text(review, "ai", templates, None) == (None, "")


def test_settings_mode_needs_the_master_switch() -> None:
    settings = ReviewSettings(auto_enabled=False, modes={5: "template"})
    assert settings.mode_for(5) == "off"
    settings.auto_enabled = True
    assert settings.mode_for(5) == "template" and settings.mode_for(1) == "off"


def test_prompt_mentions_a_rating_only_review() -> None:
    _, user = review_reply_prompt(rating=2, product="Шнур")
    assert "Оценка: 2 из 5 (негативный)" in user and "только оценку" in user
    _, user = review_reply_prompt(rating=5, text="Супер", cons="маловато")
    assert "Отзыв: Супер" in user and "Недостатки: маловато" in user


def test_clean_reply_strips_wrapping() -> None:
    assert clean_reply("«**Спасибо** за отзыв!»") == "Спасибо за отзыв!"
    assert clean_reply(" . ") is None


def test_parse_wb_feedback() -> None:
    item = {
        "id": "fb1",
        "text": "",
        "pros": "",
        "cons": "",
        "productValuation": 5,
        "createdDate": "2026-10-17T10:00:00Z",
        "answer": None,
        "productDetails": {
            "nmId": 148488568,
            "supplierArticle": "btn30",
            "productName": "Пуговицы",
        },
        "photoLinks": [{"fullSize": "x"}],
        "userName": "Анна",
    }
    row = parse_wb_feedback(item, account_id="default", synced_at=NOW)
    assert (row["review_id"], row["product_id"], row["offer_id"]) == ("fb1", "148488568", "btn30")
    assert (row["rating"], row["has_text"], row["is_answered"], row["photos"]) == (5, 0, 0, 1)
    assert row["created_at"] == datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    answered = parse_wb_feedback(
        {**item, "text": "ok", "answer": {"text": "Спасибо!"}}, account_id="default", synced_at=NOW
    )
    assert (answered["has_text"], answered["is_answered"], answered["answer_text"]) == (
        1,
        1,
        "Спасибо!",
    )


def test_parse_ozon_review() -> None:
    item = {
        "id": "r1",
        "sku": 2002,
        "text": "",
        "rating": 4,
        "published_at": "2026-10-16T08:30:00.123Z",
        "status": "UNPROCESSED",
        "comments_amount": 0,
        "photos_amount": 2,
    }
    row = parse_ozon_review(item, account_id="default", synced_at=NOW)
    assert (row["product_id"], row["rating"], row["has_text"], row["is_answered"]) == (
        "2002",
        4,
        0,
        0,
    )
    assert row["photos"] == 2
    processed = parse_ozon_review({**item, "status": "PROCESSED"}, account_id="d", synced_at=NOW)
    assert processed["is_answered"] == 1


def test_article_table_skips_empty_template_cells() -> None:
    text = "Артикул продавца\tЖелаемая цена для МП (WB)\nbtn1\t\nbtn2\t450\n\t\n"
    values, errors = parse_article_table(text, "цена")
    assert values == {"btn2": 450.0} and errors == []
