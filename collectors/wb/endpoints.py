"""WB endpoints metadata."""

from __future__ import annotations

STATISTICS_BASE_URL = "https://statistics-api.wildberries.ru"
ANALYTICS_BASE_URL = "https://seller-analytics-api.wildberries.ru"

SALES_PATH = "/api/v1/supplier/sales"
ORDERS_PATH = "/api/v1/supplier/orders"
# /api/v1/supplier/stocks was switched off on 2026-06-23; the analytics report replaces it
STOCKS_PATH = "/api/analytics/v1/stocks-report/wb-warehouses"
STOCKS_PAGE_LIMIT = 250000
# v2 /api/v2/nm-report/detail was removed by WB (404); v3 returns per-period totals per card
FUNNEL_PATH = "/api/analytics/v3/sales-funnel/products"
FUNNEL_PAGE_LIMIT = 1000

# Write APIs (verified against WB OpenAPI specs, 2026)
MARKETPLACE_BASE_URL = "https://marketplace-api.wildberries.ru"
PRICES_BASE_URL = "https://discounts-prices-api.wildberries.ru"
ADVERT_BASE_URL = "https://advert-api.wildberries.ru"

STOCKS_WRITE_PATH = "/api/v3/stocks/{warehouse_id}"  # PUT {"stocks": [{"chrtId", "amount"}]}
PRICES_UPLOAD_PATH = "/api/v2/upload/task"  # POST {"data": [{"nmID", "price"}]}
BIDS_PATH = "/api/advert/v1/bids"  # PATCH {"bids": [{"advert_id", "nm_bids": [...]}]}
