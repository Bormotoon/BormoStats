# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/); database migrations are listed per release.

## [Unreleased]

### Added

- Repricer: a "desired price" (`buyer_price`) rule can act while its card has too few sales to
  measure the marketplace's discount (`no_discount_fallback`): by the account's median discount
  (`account_median`) or keeping the desired price as the seller's price (`seller_price`) until
  the discount is measured. Off by default — the rule waits for sales, as before. Chosen per
  card under the desired price ("без продаж: …"), and in `PUT /pricing/target/{mp}/{offer}`.

### Changed

- Repricer on Ozon: a desired-price rule on a card with fewer than 3 sales keeps the desired
  price as the seller's price (`seller_price`) instead of waiting for sales; from the 3rd sale
  it prices on the card's measured discount. New Ozon rules get it (from the file upload, the
  prices page and `POST /repricer/rules` without `no_discount_fallback`) and migration 0037
  moves the waiting Ozon rules to it. "ждать продаж" can still be chosen per card; WB rules
  wait for sales by default, as before.
- Repricer on Ozon: a desired-price rule prices on the card's own discount from its first
  sale, not its third. Ozon kept discounting cards with 1–2 sales by ~50 % after their prices
  were lowered to the desired one, so buyers paid half of it; only cards without sales keep the
  desired price as the seller's.

### Fixed

- Prices: a rule that waits for sales to measure the discount is shown as "не действует: ждёт
  продаж для замера скидки" instead of "держится на площадке", and the marketplace panel
  counts such rules.
- Prices and repricer on Ozon: an Ozon card without its own sales no longer gets the account's
  median discount. Ozon's discount is mostly its "баллы за скидки", which Ozon gives per card
  — from none to ~55% on one account, next to none on new cards — so the median of ~51% made
  the repricer double the price of new cards (a desired 399,75 ₽ became 814 ₽ while buyers saw
  814 ₽). Such a card shows no discount and no buyer price; `account_median` is refused on Ozon
  (422) and is no longer offered there, and an Ozon rule that had it keeps the desired price
  as the seller's price.

### Migrations

- `0035_price_rule_fallback`: `dim_price_rule.no_discount_fallback`.
- `0036_ozon_no_account_median`: Ozon rules with `account_median` move to `seller_price`.
- `0037_ozon_rules_seller_price_until_sales`: Ozon rules that waited for sales move to
  `seller_price`.

### Changed

- Prices, from the customer's wishes of 2026-10-18: the "Шаблон Excel" of desired prices (per
  marketplace) and of cost prices hold only the two headers — "Артикул продавца" and the price
  or cost — with no prefilled articles, titles or current prices, so the seller pastes their
  own two columns under them. The article column is formatted as text and the value column as
  money. The template of desired prices downloads before the catalogue is loaded too.
- After an upload the loaded articles are highlighted in the price table (marked "загружено из
  файла") and in the cost list, with a "Показать только загруженные" filter. The import
  results of `POST /pricing/targets/import` and `POST /pricing/costs/import` list them in
  `updated`.

## [1.2.0] — 2026-10-18

Collectors moved to the current marketplace APIs; several methods they used were switched off
and every run was logged as `skipped` instead of failing. New: the finance block, login
sessions, the history store, the prices page with a repricer that keeps a desired price, the
reviews page with auto replies, Excel export and import, and the customer's UI fixes.

Upgrading: take a ClickHouse backup first. The server image moves from 26.2 to 26.3 LTS and
Redis from 7.4 to 8.10. Then apply migrations `0027`–`0034` (see Migrations; `0029` is
destructive) and rebuild the stack.

### Breaking changes

- **Ozon ads use the Performance API.** `OZON_PERF_API_KEY` is gone: create an API client in the
  Ozon ad cabinet and set `OZON_PERF_CLIENT_ID` / `OZON_PERF_CLIENT_SECRET`. The previous
  `/v1/advertising/statistics` call never existed in the Seller API.
- **Ozon `ozon_product_id` is the SKU** in postings, stocks and finance (postings and accruals
  carry no `product_id`, so it was stored as `0`).
- Ozon HTTP 404/405 now fail the task. Only 403 (missing role or subscription) is logged as a
  capability skip, so a switched-off method is visible in alerts.

### Added

- **Reviews page** ("Работа с отзывами"). WB feedbacks and Ozon reviews are collected every
  15 minutes (`tasks.reviews.sync_reviews`, queue `marketplace_actions`). Reviews with text are
  answered from the page: an AI draft, a random template of the rating or a reply typed by
  hand, sent at once. Reviews with only a rating can be answered automatically: per rating
  1–5 a mode (off, a random template, an AI reply) behind a master switch, off by default;
  at most `REVIEW_AUTO_REPLIES_PER_RUN` per run, reviews up to 30 days old, one reply per
  review, a failed one retried after 6 h. Templates per rating, for reviews with and without
  text, start from a ready-made list and can be added, edited and deleted; `{имя}` and
  `{товар}` are filled in. WB needs a token with the "Вопросы и отзывы" category
  (`WB_TOKEN_FEEDBACKS`, else `WB_TOKEN_CONTENT`); Ozon's Review API needs the Premium Plus
  subscription, otherwise the page says the method is unavailable. AI drafts need
  `AI_API_URL` / `AI_API_KEY`.
- **Excel**: every analytics table (sales, finance by day, stocks, stocks by warehouse,
  funnel, ads, price comparison) has a filter under each column (text, `> 100`, `10-20`),
  sorting by a header click and "Скачать в Excel" of the shown rows (`.xlsx` written in the
  browser, real dates and numbers, a frozen header with an autofilter). The finance breakdown
  downloads as Excel too.
- **Prices**: desired prices of a marketplace and cost prices upload from an Excel/CSV file of
  two columns (`POST /pricing/targets/import`, the cost import accepts files); a template with
  the current articles downloads from the page. "Держать цены на WB/Ozon" switches every
  desired price of the marketplace live or back to simulation (`POST /pricing/targets/keep`,
  needs `execute_marketplace`); the page warns while `MARKETPLACE_ACTIONS_ENABLED` is off.
- The shop name (the organization's name) is shown in the header; admins rename it in
  Settings (`PUT /users/me/organization`); `/users/me` returns `organization_name`.

### Changed

- Web UI, from the customer's second walkthrough:
  - Clicking "Фильтры" blanked the page (a string default was called as a function), and Back
    did not help. The filters are replaced by a period bar always on top of the dashboard,
    sales, finance, funnel and ads (7/30/90 days, half a year, a year, or dates); the default
    stays the last 30 days and every card and table names its dates.
  - The marketplace switcher reads "Все площадки" / WB / Ozon.
  - Tables: "Дата" in `dd.mm.yyyy` on one line, Russian headers everywhere, no "Кабинет"
    column, seller article and photo on sales, stocks and funnel; the "Записей" cards are gone.
  - Sales: payout by day on the revenue chart.
  - Finance: a balance card says when it was taken and, for Ozon, since which payout it has
    accrued (`/finance/balance` returns `last_payout_day`).
  - Stocks: totals in "шт", per marketplace, a table by warehouse with names
    (`/stocks/current` returns `warehouse_name`, `offer_id`, `image_url`); low stock is
    highlighted in the table instead of a separate card; the top chart is labelled by article.
  - Prices: the "Новые цены держат" mode selector is gone — a desired price is always the
    price the buyer sees; headers centred; photo and column filters on the comparison.
  - Cost and price import errors are in Russian; empty cells of a template are skipped.

- **Repricer** keeps a desired price: `buyer_price` (compensates the marketplace's discount),
  `seller_price` or `margin`, never below break-even, at most `max_step_pct` per change, and
  waits for the next catalogue snapshot after a live change. It read `mrt_breakeven_daily`,
  which nothing ever wrote, so no rule could act before. Rules now name cards by supplier
  article. See `docs/marketplace_actions.md`.

- Web UI, from a user's walkthrough: a signed-in user on a platform-only page (watermarks, task
  runs) got a 401 and was signed out, and signed out again right after signing in, since the
  page stayed in the address bar. `/api/v1/admin/*`, `/organizations`, `/costs` and `/ai` now
  answer a valid non-platform key or session with 403 (an unknown key is still 401), and the
  menu hides those pages from users.
- The account switcher filters by marketplace and account together: both seeded accounts are
  `default`, so picking one showed both marketplaces. Migration `0032` renames the seeded
  titles "WB default" / "Ozon default" to "WB" / "Ozon" (titles stay editable through
  `PATCH /organizations/{org}/accounts/{marketplace}/{account}`).
- Dashboard: every figure names its period (dates), balances show their snapshot time, charts
  label money axes in roubles with thousands separators and dates as `dd.mm.yyyy`; the top 10
  is numbered and shows the photo, name and seller article. Table headers are translated.
- `dim_product.image_url` (migration `0032`) from the catalogue; the CSP allows images from the
  WB and Ozon CDNs.

- Ozon finance: `/v3/finance/transaction/list` (switched off 2026-09-08) → `/v1/finance/accrual/by-day`
  with `last_id` pagination per Moscow day, labels from `/v1/finance/accrual/types`. One row per
  `accrual_id` with the signed `total_amount`; the nested breakdown stays in the payload. Every
  run re-reads the last 3 days. For days collected this way the staging transform drops legacy
  transaction rows, so re-collecting old periods does not double count.
- Ozon postings: `/v3/posting/fbs/list` and `/v2/posting/fbo/list` (switched off 2026-08-31) →
  `/v4/posting/fbs/list` and `/v3/posting/fbo/list` with cursor pagination; price is read from the
  money object, payout from `financial_data`, warehouse from `delivery_method` / `analytics_data`.
- Ozon stocks: `/v1/product/info/stocks` → `/v4/product/info/stocks` (FBS, rFBS, FBP) plus
  `/v1/analytics/stocks` for FBO stocks per Ozon warehouse.
- WB stocks: `/api/v1/supplier/stocks` (switched off 2026-06-23) →
  `/api/analytics/v1/stocks-report/wb-warehouses` with `WB_TOKEN_ANALYTICS`.
- WB funnel: `/api/v2/nm-report/detail` → `/api/analytics/v3/sales-funnel/products`, one request
  per day.
- `make check-tokens` probes the new Ozon postings, finance and Performance API token methods.

### Added

- **Prices page** ("Цены"): per card the crossed-out price, the seller's discount and price, the
  marketplace's discount (WB SPP, Ozon co-financed discounts) measured on recent sales, the
  buyer's price, fees, cost price and margin; a WB / Ozon comparison by supplier article; cost
  prices entered in place or pasted from a spreadsheet. API: `/api/v1/pricing/*`.

- **Analytics query cache.** `sales`, `stocks`, `funnel`, `ads` and `kpis` results are cached in
  Redis per organization and parameters for `QUERY_CACHE_TTL_SECONDS` (300 s; `0` disables).
  A successful mart rebuild or a shop account change invalidates every entry at once. The cache
  fails open: if Redis is unavailable, queries go to ClickHouse and the cache pauses for 30 s.
  Metric: `backend_query_cache_requests_total{query,result}`.
- **UI asset caching.** Content-hashed bundles under `/ui/assets/` are served with
  `Cache-Control: public, max-age=31536000, immutable`, `index.html` with `no-cache` (revalidated
  via ETag, so a deploy is picked up on the next load). nginx keeps hashed bundles in a proxy cache
  and gzips UI responses; API responses are neither cached nor compressed by the proxy.

- **History store** ([docs/history.md](docs/history.md)): a git-like, append-only archive in
  ClickHouse (`hist_objects`, `hist_commits`, `hist_refs`, `hist_changes`).
  - Hourly snapshots of every product card (WB Content + Prices API, Ozon product info, attributes
    and prices) commit only what changed, with field-level diffs (price, characteristics, photo
    URLs, …) and tombstone commits when a product disappears.
  - Every row the collectors ingest is archived by version, so revisions that `raw_*`
    (`ReplacingMergeTree`) collapses, and rows the marketplaces later drop, are kept forever.
  - `GET /api/v1/history/{repos,commits,commits/{id},snapshot,changes}` (log / show / checkout / log -p).
  - `prune_old_raw` no longer deletes from a raw table until its existing rows were imported by
    `tasks.history.backfill_raw_archive`.
  - New settings: `WB_TOKEN_CONTENT`, `HISTORY_ENABLED`, `HISTORY_PRODUCT_IGNORE_PATHS`,
    `HISTORY_STAT_IGNORE_PATHS`.
- **Finance block** ([docs/data_catalog.md](docs/data_catalog.md#finance)): the balance and the
  amount to withdraw as the seller cabinets show them, payouts (Ozon), and every charge per day —
  commission, acquiring, logistics, reverse logistics, storage, acceptance, penalties, other —
  adding up to the net accrual. Sources: Ozon `/v1/finance/balance` (daily, 730-day backfill),
  WB realization reports (`/api/finance/v1/sales-reports/detailed`; the v5
  `reportDetailByPeriod` is switched off) and the WB balance widget. `GET /api/v1/finance/daily`,
  `GET /api/v1/finance/balance`, a "Финансы" page and balance cards on the dashboard. Backfill
  datasets `ozon/balance` and `wb/finance`. Optional `WB_TOKEN_FINANCE` (defaults to the
  statistics token).
- **Point-in-time history of everything collected:** the finance tables join the archive,
  `GET /api/v1/history/state` returns every record of a dataset as it was at any moment, and the
  "История" page shows it. WB card history runs with `WB_TOKEN_CONTENT`; entities re-keyed by
  0029 are retired with a reason; reordered id-matched lists are no longer commits.
- **P&L is built** from the finance block: revenue, returns, commission, logistics, storage,
  other charges, the marketplaces' accrual, cost of goods, Ozon ads and indirect expenses.
- The sales page no longer calls the amount after commission "К выплате".
- **Several stacks on one host.** Scripts (`bootstrap`, `backup`, `restore_check`, `run_local`)
  and the Makefile take `ENV_FILE`; the app containers read `APP_ENV_FILE` (see
  [docs/environments.md](docs/environments.md#running-an-environment-from-its-own-env-file)).
- Container logs rotate (`LOG_MAX_SIZE`, default `20m`; `LOG_MAX_FILES`, default `5`).
- `gen_tls_cert.sh` writes an IP SAN when `TLS_SERVER_NAME` is an IPv4 address, so the UI can be
  opened by LAN address.
- Backfill limits follow the marketplace history depth: WB funnel 364 days, Ozon postings,
  Ozon finance and marts 730 days (WB sales/orders stay at 90, the Statistics API limit).

### Fixed

- Ozon price changes sent `old_price: "0"` and dropped the card's crossed-out price; WB price
  changes now send the card's discount along with the price.
- `sys_task_runs` times were written as naive datetimes, which ClickHouse read in its own
  timezone: on a server outside UTC every task run was off by the server's UTC offset (2 h on
  `Europe/Warsaw`), skewing freshness and data-quality windows. Rows written before the fix
  keep the offset.

- **Products had no names.** Profit and supply planning took names from the empty
  `raw_competitor_products`, and `dim_product` held no WB title at all (only cards seen in
  sales). The dictionary is now also built from the catalogue in the history store (every card
  with title, brand, WB category), the marts take names from it, and `/sales/daily` and
  `/stocks/current` return `title`.
- Ozon FBO stocks (`/v1/analytics/stocks`) are paced between SKU batches and a batch refused
  with 429 is retried after the per-minute window; about one snapshot in ten used to fail.
- The data quality report failed to serialize `date` samples, so the issue it found was lost.
- **Backend descriptor leak.** Every operational-metrics refresh opened a ClickHouse pool that
  `close()` never released (clickhouse-connect treats a passed-in pool as shared), so the backend
  hit `Too many open files` within a day and turned unhealthy.
- **App containers always read `.env`**, whatever `--env-file` said, so a second stack started with
  the first stack's secrets.
- Ozon postings are requested in 364-day windows; `/v4/posting/fbs/list` rejects exactly 365
  (`PERIOD_IS_TOO_LONG`). WB funnel backfill starts 364 days back, the oldest day WB accepts.
- A capability skip records the status, method, path and response body of the refused call.
- **Sales figures** ([docs/data_catalog.md](docs/data_catalog.md#metrics)):
  - WB payout was `incomeID` (the supply number; 2.3 billion ₽ in a month) and WB revenue was
    `forPay`. Revenue is now `priceWithDisc`, payout `forPay`.
  - WB returns (`saleID` `R…`) were counted as sales, and a return replaced its sale in
    `raw_wb_sales` (same `srid`/`nm_id`/`chrt_id`); `sale_id` joins the key.
  - Ozon sales were every posting, cancelled ones included, dated by order, with no returns,
    plus 1 206 legacy `product_id = 0` rows counted twice (revenue about three times too high).
    They now come from the realization accruals: the day of the sale, returns, actual commission.
  - Returns were stored negative (`UInt32` overflow in `mrt_profit_daily`); profit revenue ignored
    the quantity; margin was relative to the payout.
  - WB order value was `totalPrice`, the list price before every discount.
- **Stocks and supply planning:** no Ozon stock was ever stored (negative FBO warehouse ids on a
  `UInt64` column); WB stock was per size while sales are per card, so WB never matched; "average
  daily sales" was the average quantity per order line; the latest stock was one warehouse's.
- **Days are Moscow days.** WB times (Moscow wall-clock without an offset) were read as UTC and
  days were taken in the server time zone, so late-evening sales moved to the next day.
- **Reads during a rebuild:** the API summed marts without `FINAL`, and the rebuild's
  `SET mutations_sync` was lost between HTTP requests, so totals could double until merges ran.
- ABC/XYZ was never built (no task ran it), the API returned every daily snapshot, and XYZ
  skipped days without sales; it now uses weekly quantities over 8 full weeks.
- The UI summed only the first page of results and averaged per-row ratios (conversion, ACOS,
  margin); "top products" were product-days; the default period was 31 UTC days.
- Data-quality checks compared times across conventions (false "future" sales) and flagged WB
  funnels with more orders than cart adds, which WB allows (one-click orders).

### Security

- Python runtime of the backend and worker images 3.14.3 → 3.14.8: fixes CVE-2025-12781,
  CVE-2025-15366, CVE-2026-2297 (their waivers had expired) and 11 other high/critical CPython
  findings. CVE-2025-15367 (`poplib`, unused) is still reported on every released CPython,
  3.15.0 included; its waiver runs to 2027-01-15.
- Frontend build dependency `source-map-js` updated (GHSA-68fv-2mgg-jv7q, high).
- urllib3 2.7.0 → 2.8.0 (GHSA-8988-9cw3-xx77, GHSA-vxq7-64xx-v4gw high; GHSA-gh4c-6fx4-qh6g).
  It had turned the supply-chain gate red on `main`.
- Code scanning gets only fixable image findings. The 326 open Grype alerts were Debian base
  packages marked wont-fix; the full list stays in the image SBOM artifacts, and the blocking
  gate (high, fixable) is unchanged.

### Dependencies

- Images: ClickHouse 26.2 → **26.3.55.2 LTS**, Redis 7.4.7 → 8.10.2, nginx 1.27.5 → 1.31.0,
  the frontend build stage on node 26. ClickHouse builds after 26.3 need AVX2 (x86-64-v3)
  and die with "Illegal instruction" on CPUs without it (an Intel i7-3770 runs production);
  Dependabot ignores ClickHouse ≥ 26.4.
- Python: redis-py 8.1, pydantic 2.14, pydantic-settings 2.16, celery 5.6.3, uvicorn 0.54,
  structlog 26.1, cryptography 50.0.2, prometheus-client 0.26, tzdata 2026.5; dev: mypy 2.4,
  ruff 0.17, pytest 9.1, pip-audit 2.10.1. `httpx2` joins the dev lock: starlette 1.3's
  TestClient needs it, and without it CI could not collect the tests.
- Frontend: react 19.3, recharts 3.10, motion 14, vite 8.3, Playwright 1.64.
- Not taken yet: FastAPI 0.143 (routes of included routers left `app.routes`, so the audit
  trail and metrics lost `/api/v1` and the auth-matrix test saw one route) and
  clickhouse-connect 1.x (closing a client no longer frees its own pool). Dependabot ignores
  both until they are adapted.
- Dependabot groups minor and patch Python updates into one weekly PR.
- The Playwright smoke tests follow the sign-in screen added on 2026-10-05.

### Migrations

- `0034_reviews`: `fct_review`, `sys_review_reply`, `dim_review_settings`,
  `dim_review_template`, `sys_review_sync`. Reviews appear after the first sync run.
- `0033_pricing`: `dim_offer_cost` (cost price by supplier article per organization, used by
  profit and P&L before the platform-level `dim_product_cost`), `v_offer_cost`,
  `mrt_price_current`, and `mode` / `target_price` / `max_step_pct` on `dim_price_rule`.
  The price breakdown fills on the next marts run; enter cost prices on the Prices page.

- `0032_product_image_account_titles`: `dim_product.image_url`; renames the seeded account
  titles. Afterwards run a transform (the catalogue sync fills the photos).
- `0031_login`: `dim_user_credential` (password hashes) and `sys_user_session` (sign-in
  sessions next to API keys).
- `0030_finance`: `raw_ozon_finance_balance`, `raw_wb_sales_report`, `raw_marketplace_balance`,
  `mrt_finance_daily`; `mrt_pnl_monthly` gains `storage_rub`, `other_costs_rub`,
  `net_accrued_rub`, `cogs_rub`. Afterwards run the `ozon/balance` and `wb/finance` backfills
  and a marts backfill.
- `0029_sales_math_fixes` (destructive: rebuilds `raw_wb_sales` with `sale_id`, recreates
  `raw_ozon_stocks` — empty — and the `stg_sales`/`stg_orders`/`stg_stocks`/`mrt_stock_daily`
  tables, deletes the duplicate Ozon posting items). Afterwards run the transform and marts
  backfills for 730 days and a 90-day WB sales backfill; take a backup first.
- `0028_history`: the four `hist_*` tables (rollback drops them; take a backup first).
- `0027_ozon_finance_accruals`: `raw_ozon_finance_ops.source` (`transaction_list_v3` for existing
  rows, `accrual_by_day` for new ones).

## [1.1.0] — 2026-09-29

Remediation of the September 2026 audit (`AUDIT_REPORT.md`); details per finding in
[docs/audit_remediation.md](docs/audit_remediation.md).

### Breaking changes

- **Every `/api/v1/*` endpoint requires `X-API-Key`.** Analytics reads were anonymous before;
  `PUBLIC_READ_API=true` restores that for local development only (rejected in stage/prod).
- **User API keys are hashed.** Existing plaintext keys keep working (migration `0021` converts
  them, they are upgraded to scrypt on first use), but keys are no longer returned by
  `GET /users`; new keys are shown once on create/rotate. New format: `bsk_<id>_<secret>`.
- **Tenancy comes from the key.** `organization_id` in request bodies (users, expenses) is ignored/removed;
  the platform key selects an organization with `X-Organization-Id`.
- A user without a membership row in its organization now gets 403 (was treated as viewer).
- Webhook secrets are server-generated, encrypted at rest and returned once; migration `0024`
  clears previously stored plaintext secrets — rotate existing subscriptions.
- Bidder/repricer rules default to **dry-run**; live changes need `execute:marketplace` and
  `MARKETPLACE_ACTIONS_ENABLED=true`.
- Compose requires `REDIS_PASSWORD` and `BOOTSTRAP_CH_ADMIN_PASSWORD`; Redis uses an ACL user
  (`REDIS_USERNAME`, default `bormostats`).
- `apply_migrations.py --rollback` was replaced by `apply_migrations.py rollback --target V`.
- WB stock push now uses the Marketplace API and `WB_TOKEN_MARKETPLACE`; `sku` must be the
  numeric size id (`chrtId`).

### Added

- `AuthContext` with an explicit role matrix and scopes; `/users/me` principal info; key expiry,
  revocation and org-wide revoke; admin network allowlist; audit log of all mutating requests.
- Webhook delivery engine: HMAC-SHA256 signatures with timestamp, idempotency key, retries with
  backoff, dead letters, SSRF protection with IP pinning, test delivery and secret rotation.
- Real marketplace clients for WB bids/prices/stocks and Ozon prices/stocks with dry-run,
  idempotency, per-run budget, kill switch and `sys_marketplace_actions` audit trail.
- Insights: per-organization triggers, dedupe keys, full UUIDs, `insight.created` events.
- Async CSV exports (`/api/v1/exports`), data freshness endpoint and UI banner.
- `/health/live`, `/health/ready` (cached), `/health/dependencies`; protected `/metrics`
  (bearer token, background refresh); authenticated `/api/v1/openapi.json`.
- Request correlation (`X-Request-ID`) across proxy → API → Celery; HTTP and ClickHouse metrics.
- Data-quality metrics (freshness, row counts, null rates, schema drift) and new alerts
  (stale marts, schema drift, retry storms, 429/5xx rates, webhook dead letters, action failures).
- Migration runner: lock, journal, checksums, postconditions, manifest, `status`/`verify`/`rollback`.
- `make init ENV=…`, `make backup`, `make restore-check`, `make lock`, `make check-frontend`.
- `*_FILE` secret loading (Docker/Kubernetes secrets).
- Tests: auth matrix over every route, tenant isolation on real ClickHouse, SQL contracts for
  rules/triggers/exports, worker suite, Playwright E2E smoke, browser-extension tests.

### Fixed

- `str.format` over SQL with ClickHouse binds crashed bidder campaign sync, insights task
  updates and all organization/member/shop-account writes.
- Celery workers only consumed the `etl` queue: WB/Ozon/competitor/automation tasks never ran.
- Bidder/repricer/insights tasks could not be imported and were never registered.
- Enum roles returned by ClickHouse by name broke user authentication.
- Insights turnover trigger and `turnover_alert` rule queried a non-existent column;
  `now() - 14` subtracted seconds instead of days.
- Naive UTC datetimes were shifted by the process timezone when bound to ClickHouse.
- `make up` passed a wrong `.env` path; the HTTP→HTTPS redirect used the container port;
  the proxy kept a stale backend IP after a backend restart.
- ClickHouse readiness gauge was always 0 (missing `system.disks` grant).
- WB stock updates were posted to the read-only Statistics API; product-cost upsert crashed;
  PIM product search referenced an unknown alias.
- Frontend: key entered in settings was ignored until reload; bid sliders fired a request per
  pixel; `make frontend` removed a directory outside the repository.
- Browser extension: DOM-injection of scraped data, API key in synced storage, content script
  calling the API directly, competitor-price payload rejected by the API.
- Rate limiter returned 500 instead of 429 and shared one bucket between all clients.

### Security

- npm advisories fixed (react-router 7.18.4, postcss 8.5.28, nanoid 3.3.19).
- Python dependencies split into `requirements.in` + hash-locked `requirements.txt`.
- CI: actions pinned to commit SHAs, blocking `pip-audit`/Grype gate with expiring waivers,
  SARIF upload, SBOM retention, `npm audit`.

### Migrations

`0021_api_key_hashing`, `0022_marketplace_actions`, `0023_insights_dedupe`,
`0024_webhook_delivery`, `0025_audit_actor`, `0026_export_jobs` (all with rollback scripts).

## [1.0.0] — 2026-06-25

Initial public release.
