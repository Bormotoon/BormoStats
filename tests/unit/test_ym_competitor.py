from __future__ import annotations

import pytest

from collectors.competitor.ym import parse_ym_page


def test_json_ld_search_preserves_sku_and_positions() -> None:
    html = """<script type="application/ld+json">{"@type":"ItemList", "itemListElement":[
        {"item":{"@type":"Product","sku":"123","name":"Product", "offers":
        {"price":"1200.50", "availability":"https://schema.org/InStock"}}}]}</script>"""
    products, prices, positions = parse_ym_page(html, "run", query="Product")
    assert products[0]["marketplace"] == "ym"
    assert products[0]["product_id"] == 123
    assert prices[0]["price_rub"] == 1200.5
    assert positions[0]["position"] == 1


def test_captcha_does_not_become_successful_empty_snapshot() -> None:
    with pytest.raises(ValueError, match="CAPTCHA"):
        parse_ym_page("<html>Verify you are human</html>", "run")
