"""Public Market cards/search from JSON-LD; CAPTCHA pages fail explicitly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import httpx


class _JsonLd(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.buffer = ""
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.active, self.buffer = True, ""

    def handle_data(self, data: str) -> None:
        if self.active:
            self.buffer += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.active:
            self.active = False
            self.documents.append(json.loads(self.buffer))


def _products(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [p for item in value for p in _products(item)]
    if not isinstance(value, dict):
        return []
    if value.get("@type") == "Product":
        return [value]
    return [p for key in ("@graph", "itemListElement", "item") for p in _products(value.get(key))]


def parse_ym_page(
    html: str, run_id: str, *, query: str = "", page: int = 1
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    parser = _JsonLd()
    parser.feed(html)
    products, prices, positions = [], [], []
    now = datetime.now(UTC)
    seen: set[int] = set()
    for item in _products(parser.documents):
        sku = str(item.get("sku") or "")
        if not sku.isdigit() or int(sku) in seen:
            continue
        pid = int(sku)
        seen.add(pid)
        offer = item.get("offers") or {}
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        price = float(offer.get("price") or offer.get("lowPrice") or 0)
        rating = item.get("aggregateRating") or {}
        brand = item.get("brand") or {}
        payload = json.dumps(item, ensure_ascii=False)
        products.append(
            dict(
                run_id=run_id,
                marketplace="ym",
                product_id=pid,
                name=str(item.get("name") or ""),
                brand=str(brand.get("name", "") if isinstance(brand, dict) else brand),
                category_id=0,
                category_name=str(item.get("category") or ""),
                supplier_id=0,
                supplier_name="",
                rating=float(rating.get("ratingValue") or 0),
                review_count=int(rating.get("reviewCount") or 0),
                payload=payload,
                updated_at=now,
            )
        )
        if price > 0:
            prices.append(
                dict(
                    run_id=run_id,
                    marketplace="ym",
                    product_id=pid,
                    price_rub=price,
                    price_old_rub=price,
                    sale_percent=0,
                    in_stock=int(str(offer.get("availability", "")).endswith("InStock")),
                    snapshot_ts=now,
                    payload=payload,
                )
            )
        if query:
            positions.append(
                dict(
                    run_id=run_id,
                    marketplace="ym",
                    query=query,
                    search_page=page,
                    position=len(products),
                    product_id=pid,
                    price_rub=price,
                    snapshot_ts=now,
                    ingested_at=now,
                )
            )
    if not products:
        raise ValueError(
            "Market page has no identifiable JSON-LD products (CAPTCHA or changed markup)"
        )
    return products, prices, positions


class YmPublicClient:
    def page(self, *, sku: str = "", query: str = "", page: int = 1) -> str:
        params = {"text": query, "page": str(page)} if query else {"sku": sku}
        response = httpx.get(
            "https://market.yandex.ru/search?" + urlencode(params),
            timeout=30,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
