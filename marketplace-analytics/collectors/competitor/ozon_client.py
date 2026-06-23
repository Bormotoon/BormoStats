"""Public Ozon API client for competitor product data."""

from __future__ import annotations

from typing import Any

from collectors.common.http_client import JsonHttpClient

OZON_PUBLIC_BASE_URL = "https://www.ozon.ru"
OZON_COMPOSER_PATH = "/api/composer-api.bx/page/json/v2"
OZON_API_TIMEOUT = 30
OZON_MAX_ATTEMPTS = 3


class OzonPublicApiClient:
    """Client for Ozon public (non-authenticated) API endpoints."""

    def __init__(self) -> None:
        self._client = JsonHttpClient(
            base_url=OZON_PUBLIC_BASE_URL,
            marketplace="ozon_public",
            timeout_seconds=OZON_API_TIMEOUT,
            max_attempts=OZON_MAX_ATTEMPTS,
            circuit_failure_threshold=10,
            circuit_reset_seconds=120,
        )

    def close(self) -> None:
        self._client.close()

    def product_card(self, product_id: int) -> dict[str, Any] | None:
        """Fetch Ozon product card details.

        Returns the raw JSON state from the Ozon composer API, or None on failure.
        """
        params = {"url": f"/product/{product_id}/"}
        result = self._client.get(OZON_COMPOSER_PATH, params=params)
        if not isinstance(result, dict):
            return None
        return result

    def product_cards_batch(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch multiple Ozon product cards.

        Ozon's API only supports single-product lookups, so we make one
        request per product. Returns a list of raw state dicts.
        """
        results: list[dict[str, Any]] = []
        for pid in product_ids:
            try:
                card = self.product_card(pid)
                if card is not None:
                    results.append(card)
            except Exception:
                pass
        return results
