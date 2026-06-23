"""Public WB API client for competitor product data."""

from __future__ import annotations

from typing import Any

from collectors.common.http_client import JsonHttpClient
from collectors.competitor.endpoints import (
    WB_CARD_BATCH_SIZE,
    WB_CARD_DETAIL_PATH,
    WB_DEST,
    WB_PUBLIC_BASE_URL,
)


class WbPublicApiClient:
    """Client for WB public (non-authenticated) API endpoints."""

    def __init__(self) -> None:
        self._card_client = JsonHttpClient(
            base_url=WB_PUBLIC_BASE_URL,
            marketplace="wb_public",
            max_attempts=3,
            circuit_failure_threshold=10,
            circuit_reset_seconds=120,
        )

    def close(self) -> None:
        self._card_client.close()

    def product_cards(self, nm_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch product card details for up to 100 nm_ids at a time.

        Returns a list of raw product dicts from the WB card API.
        """
        if not nm_ids:
            return []

        products: list[dict[str, Any]] = []
        for offset in range(0, len(nm_ids), WB_CARD_BATCH_SIZE):
            batch = nm_ids[offset : offset + WB_CARD_BATCH_SIZE]
            ids_param = ";".join(str(i) for i in batch)
            params = {
                "appType": "1",
                "curr": "rub",
                "dest": WB_DEST,
                "spp": "30",
                "nm": ids_param,
            }
            result = self._card_client.get(WB_CARD_DETAIL_PATH, params=params)
            if isinstance(result, dict):
                batch_products = result.get("data", {}).get("products", [])
                if isinstance(batch_products, list):
                    products.extend(batch_products)
        return products

    def product_cards_by_id(self, nm_ids: list[int]) -> list[dict[str, Any]]:
        """Alias for product_cards()."""
        return self.product_cards(nm_ids)
