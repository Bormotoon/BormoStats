"""Canonical documents, hashes and field diffs of the history store."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from collectors.ozon.parsers import build_ozon_products
from collectors.wb.parsers import build_wb_products
from common.history import (
    canonicalize,
    commit_id,
    diff_documents,
    dump,
    object_hash,
    strip_ignored,
)


def test_hash_ignores_key_order_and_whitespace() -> None:
    assert object_hash({"a": 1, "b": [1, 2]}) == object_hash({"b": [1, 2], "a": 1})
    assert object_hash({"a": 1}) != object_hash({"a": 2})


def test_canonicalize_handles_database_types() -> None:
    document = {
        "day": date(2026, 9, 1),
        "ts": datetime(2026, 9, 1, 10, 0, 0, 999_999),
        "aware": datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        "money": Decimal("10.50"),
        "nan": float("nan"),
        "tags": {"b", "a"},
    }
    assert canonicalize(document) == {
        "day": "2026-09-01",
        # ClickHouse DateTime has no sub-second part, so live and re-read rows must agree
        "ts": "2026-09-01T10:00:00",
        "aware": "2026-09-01T10:00:00+00:00",
        "money": "10.50",
        "nan": None,
        "tags": ["a", "b"],
    }


def test_canonicalize_rejects_unknown_types() -> None:
    with pytest.raises(TypeError):
        canonicalize({"x": object()})


def test_dump_keeps_unicode_readable() -> None:
    assert dump({"title": "Кружка"}) == '{"title":"Кружка"}'


def test_commit_id_is_deterministic_and_depends_on_parent() -> None:
    args = {"marketplace": "wb", "account_id": "a", "repo": "product", "entity_key": "1"}
    first = commit_id(**args, parent_id="", obj="h1")
    assert first == commit_id(**args, parent_id="", obj="h1")
    assert first != commit_id(**args, parent_id=first, obj="h1")


def _paths(old: object, new: object) -> list[tuple[str, str, str, str]]:
    return [(c.path, c.op, c.old, c.new) for c in diff_documents(old, new)]


def test_diff_reports_price_change_with_both_values() -> None:
    old = {"price": {"price": 1000, "discount": 10}}
    new = {"price": {"price": 900, "discount": 10}}
    assert _paths(old, new) == [("price.price", "change", "1000", "900")]


def test_diff_reports_added_and_removed_fields() -> None:
    assert _paths({"a": 1}, {"b": 2}) == [
        ("a", "remove", "1", ""),
        ("b", "add", "", "2"),
    ]


def test_diff_matches_list_items_by_identity_not_position() -> None:
    old = {"chars": [{"id": 1, "value": "red"}, {"id": 2, "value": "cotton"}]}
    new = {"chars": [{"id": 2, "value": "cotton"}, {"id": 1, "value": "blue"}]}
    assert _paths(old, new) == [("chars[id=1].value", "change", '"red"', '"blue"')]


def test_diff_reports_added_list_item() -> None:
    old = {"sizes": [{"chrtID": 1, "price": 5}]}
    new = {"sizes": [{"chrtID": 1, "price": 5}, {"chrtID": 2, "price": 6}]}
    added = dump({"chrtID": 2, "price": 6})
    assert _paths(old, new) == [("sizes[chrtID=2]", "add", "", added)]


def test_diff_treats_scalar_lists_as_one_value() -> None:
    old = {"photos": ["a.jpg", "b.jpg"]}
    new = {"photos": ["b.jpg"]}
    assert _paths(old, new) == [("photos", "change", '["a.jpg","b.jpg"]', '["b.jpg"]')]


def test_diff_of_photo_objects_is_positional() -> None:
    old = {"photos": [{"big": "1"}, {"big": "2"}]}
    new = {"photos": [{"big": "1"}]}
    assert _paths(old, new) == [("photos[1]", "remove", '{"big":"2"}', "")]


def test_equal_documents_have_no_changes() -> None:
    document = {"a": [1, {"b": None}]}
    assert diff_documents(document, dict(document)) == []


def test_strip_ignored_removes_matching_paths_only() -> None:
    document = {"card": {"updatedAt": "t", "title": "x"}, "price": {"updatedAt": "t"}}
    assert strip_ignored(document, ["card.updatedAt"]) == {
        "card": {"title": "x"},
        "price": {"updatedAt": "t"},
    }
    assert strip_ignored(document, ["*.updatedAt"]) == {"card": {"title": "x"}, "price": {}}
    assert strip_ignored(document, []) is document


def test_build_wb_products_pairs_cards_with_prices() -> None:
    cards = [{"nmID": 1, "title": "a"}, {"nmID": 2, "title": "b"}, {"title": "no id"}]
    prices = [{"nmID": 1, "sizes": [{"price": 100}]}]
    assert build_wb_products(cards, prices) == {
        "1": {"card": cards[0], "price": prices[0]},
        "2": {"card": cards[1], "price": None},
    }


def test_build_wb_products_omits_price_when_source_not_read() -> None:
    documents = build_wb_products([{"nmID": 1}], None)
    assert documents == {"1": {"card": {"nmID": 1}}}


def test_build_ozon_products_omits_sections_that_were_not_read() -> None:
    info = [{"id": 10, "name": "x"}]
    assert build_ozon_products([10], info, None, None) == {"10": {"info": info[0]}}
    full = build_ozon_products(
        [10, 11], info, [{"id": 10, "attributes": []}], [{"product_id": 10, "price": "5"}]
    )
    assert full["10"]["attributes"] == {"id": 10, "attributes": []}
    assert full["10"]["price"] == {"product_id": 10, "price": "5"}
    assert full["11"] == {"info": None, "attributes": None, "price": None}
