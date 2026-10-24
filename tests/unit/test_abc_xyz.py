from __future__ import annotations

from unittest.mock import MagicMock

from app.services.abc_xyz_service import AbcXyzService


def test_analysis_names_the_card_of_each_product() -> None:
    ch = MagicMock()
    ch.query.return_value.result_rows = [
        (
            "2026-10-24",
            "ozon",
            "default",
            "1838504005",
            17208.0,
            0.0466,
            0.0466,
            "A",
            0.29,
            0.22,
            75.6,
            "Z",
            "btn23pgf05pmg",
            "Пуговицы 23 мм 5 шт",
            "https://img/1.jpg",
        ),
        (
            "2026-10-24",
            "wb",
            "default",
            "57420767",
            1.0,
            0.1,
            1.0,
            "C",
            0,
            0,
            999,
            "Z",
            None,
            None,
            None,
        ),
    ]
    rows = AbcXyzService(ch, "org").get_analysis("ozon")
    assert [(r["offer_id"], r["title"], r["image_url"]) for r in rows] == [
        ("btn23pgf05pmg", "Пуговицы 23 мм 5 шт", "https://img/1.jpg"),
        (None, None, None),
    ]
    sql = ch.query.call_args.args[0]
    assert (
        "LEFT JOIN" in sql and "mrt_price_current" in sql and "a.marketplace = {mp:String}" in sql
    )
