"""Ozon endpoints metadata."""

from __future__ import annotations

BASE_URL = "https://api-seller.ozon.ru"

POSTINGS_FBS_LIST_PATH = "/v3/posting/fbs/list"
POSTINGS_FBO_LIST_PATH = "/v2/posting/fbo/list"
STOCKS_PATH = "/v1/product/info/stocks"
ADS_STATS_PATH = "/v1/advertising/statistics"
FINANCE_OPS_PATH = "/v3/finance/transaction/list"

# Write APIs
PRICES_IMPORT_PATH = "/v1/product/import/prices"  # POST {"prices": [{"offer_id", "price"}]}
STOCKS_WRITE_PATH = (
    "/v2/products/stocks"  # POST {"stocks": [{"offer_id", "stock", "warehouse_id"}]}
)
