"""Public marketplace API endpoints for competitor data."""

from __future__ import annotations

# WB card detail: returns name, brand, prices, stock, rating for up to 100 nm_ids
# https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=<dest>&spp=30&nm=<id1>;<id2>
WB_CARD_DETAIL_PATH = "/cards/v2/detail"

# WB search: returns search results with prices, positions
# https://search.wb.ru/exactmatch/ru/common/v7/search?query=<q>&page=<n>&dest=<dest>
WB_SEARCH_PATH = "/exactmatch/ru/common/v7/search"

# WB product card base URL (no trailing slash)
WB_PUBLIC_BASE_URL = "https://card.wb.ru"

# WB search base URL
WB_SEARCH_BASE_URL = "https://search.wb.ru"

# Common WB destination parameter (Moscow + surrounding regions)
WB_DEST = "-1029256,-1022697,-1278704,-1254908"

# Max nm_ids per card detail request
WB_CARD_BATCH_SIZE = 100

# Max search results pages to scrape per keyword
WB_SEARCH_MAX_PAGES = 5
