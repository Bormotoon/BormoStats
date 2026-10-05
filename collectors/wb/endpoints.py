"""WB endpoints metadata."""

from __future__ import annotations

from datetime import date

STATISTICS_BASE_URL = "https://statistics-api.wildberries.ru"
ANALYTICS_BASE_URL = "https://seller-analytics-api.wildberries.ru"

# Finance API (category "Финансы"; the statistics token of this account carries it).
# Every method allows one request per minute.
FINANCE_BASE_URL = "https://finance-api.wildberries.ru"
BALANCE_PATH = "/api/v1/account/balance"
# realization report lines, replacing /api/v5/supplier/reportDetailByPeriod (switched off);
# daily reports add up to the weekly ones the payouts are made from
SALES_REPORT_DETAILED_PATH = "/api/finance/v1/sales-reports/detailed"
SALES_REPORT_PAGE_LIMIT = 100000
SALES_REPORT_MAX_PAGES = 50
SALES_REPORT_EARLIEST_DAY = date(2025, 1, 1)

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

# Catalogue (history store): product cards and seller prices
CONTENT_BASE_URL = "https://content-api.wildberries.ru"
CARDS_LIST_PATH = "/content/v2/get/cards/list"  # POST, cursor pagination (updatedAt + nmID)
CARDS_PAGE_LIMIT = 100
CARDS_MAX_PAGES = 5000  # safety bound: 500k cards
PRICES_LIST_PATH = "/api/v2/list/goods/filter"  # GET on PRICES_BASE_URL, limit/offset
PRICES_PAGE_LIMIT = 1000
