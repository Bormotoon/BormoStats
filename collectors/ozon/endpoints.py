"""Ozon endpoints metadata.

Verified against the Seller API and Performance API OpenAPI specs (September 2026).
"""

from __future__ import annotations

from datetime import date

BASE_URL = "https://api-seller.ozon.ru"

# v3 FBS / v2 FBO lists were switched off on 2026-08-31; both now page with a cursor.
POSTINGS_FBS_LIST_PATH = "/v4/posting/fbs/list"
POSTINGS_FBO_LIST_PATH = "/v3/posting/fbo/list"
POSTINGS_PAGE_LIMIT = 100
# Ozon rejects posting periods longer than one year
POSTINGS_MAX_WINDOW_DAYS = 365

# FBS / rFBS / FBP stocks; FBO stocks come from the analytics method below
STOCKS_PATH = "/v4/product/info/stocks"
STOCKS_PAGE_LIMIT = 1000
FBO_STOCKS_PATH = "/v1/analytics/stocks"
FBO_STOCKS_SKU_BATCH = 100

# /v3/finance/transaction/list and /totals were switched off on 2026-09-08
FINANCE_ACCRUAL_BY_DAY_PATH = "/v1/finance/accrual/by-day"
FINANCE_ACCRUAL_TYPES_PATH = "/v1/finance/accrual/types"
FINANCE_ACCRUAL_EARLIEST_DAY = date(2022, 1, 1)
# safety bound for last_id pagination within a single day
FINANCE_ACCRUAL_MAX_PAGES_PER_DAY = 500

# Performance API (ads): separate host with OAuth client-credentials tokens
PERFORMANCE_BASE_URL = "https://api-performance.ozon.ru"
PERFORMANCE_TOKEN_PATH = "/api/client/token"
PERFORMANCE_DAILY_STATS_PATH = "/api/client/statistics/daily/json"

# Catalogue (history store)
PRODUCT_LIST_PATH = "/v3/product/list"  # last_id pagination
PRODUCT_LIST_PAGE_LIMIT = 1000
PRODUCT_INFO_LIST_PATH = "/v3/product/info/list"  # up to 1000 ids per call
PRODUCT_ATTRIBUTES_PATH = "/v4/product/info/attributes"  # last_id pagination
PRODUCT_PRICES_PATH = "/v5/product/info/prices"  # cursor pagination
PRODUCT_BATCH = 1000
PRODUCT_MAX_PAGES = 5000

# Write APIs
PRICES_IMPORT_PATH = "/v1/product/import/prices"  # POST {"prices": [{"offer_id", "price"}]}
STOCKS_WRITE_PATH = (
    "/v2/products/stocks"  # POST {"stocks": [{"offer_id", "stock", "warehouse_id"}]}
)
