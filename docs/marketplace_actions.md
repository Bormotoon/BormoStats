# Bid and price automation (bidder / repricer)

## Safety model

1. **Dry-run by default.** New rules have `dry_run=true`: changes are computed and
   recorded as `simulated`, nothing is sent to the marketplace.
2. **Explicit permission.** Switching a rule to live mode needs the
   `execute:marketplace` scope (org admin/owner or the platform key).
3. **Global kill switch.** Live writes also require `MARKETPLACE_ACTIONS_ENABLED=true`
   on the workers; otherwise they are recorded as `blocked_kill_switch`.
4. **Idempotency.** Each change has a key (rule, target, value, day). A change already
   recorded (except `failed`) is skipped, so retries and overlapping runs do not repeat it.
5. **Budget.** At most `MARKETPLACE_ACTIONS_MAX_PER_RUN` live calls per run.
6. **Audit trail.** Every outcome is stored in `sys_marketplace_actions` with before/after
   values, HTTP status and response body; see `GET /api/v1/{bidder|repricer}/actions`.
7. **Resilience.** Marketplace calls go through `JsonHttpClient` (retries with backoff on
   429/5xx honouring WB rate-limit headers, circuit breaker). Failures raise the
   `MarketplaceActionFailures` alert.

## Marketplace APIs

| Operation | Marketplace | API | Token |
|---|---|---|---|
| Bid change | WB | `PATCH advert-api.wildberries.ru/api/advert/v1/bids` (per campaign + nm_id + placement, kopecks) | `WB_TOKEN_PROMOTION` |
| Price change | WB | `POST discounts-prices-api.wildberries.ru/api/v2/upload/task` (`nmID`, list `price`, `discount` kept) | `WB_TOKEN_PRICES` |
| Price change | Ozon | `POST api-seller.ozon.ru/v1/product/import/prices` (`price`, `old_price` scaled with it) | `OZON_CLIENT_ID` / `OZON_API_KEY` |
| Stock update | WB | `PUT marketplace-api.wildberries.ru/api/v3/stocks/{warehouseId}` (`chrtId`, `amount`) | `WB_TOKEN_MARKETPLACE` |
| Stock update | Ozon | `POST api-seller.ozon.ru/v2/products/stocks` (≤100 items per call) | `OZON_CLIENT_ID` / `OZON_API_KEY` |

Ozon Performance (ad bid) changes are not integrated yet and are recorded as
`unsupported`. A WB bid rule needs `product_id` (nm_id) and `placement`
(`combined` for unified-bid campaigns, `search`/`recommendations` for manual ones).

## Repricer: what a price rule keeps

A price rule names a card by **supplier article** (`product_id` = WB `vendorCode` / Ozon
`offer_id`) and reads the card's current price breakdown from `mrt_price_current`. The
"Цены" page creates one rule per card from the desired price (`PUT /api/v1/pricing/target/
{marketplace}/{offer_id}`); `/api/v1/repricer/rules` manages them directly.

| `mode` | Seller price the rule sets |
|---|---|
| `buyer_price` | `target_price / (1 − marketplace discount)`: keeps what the buyer pays after WB SPP or Ozon's discounts. Acts on a discount measured on **3+ of the card's own sales** (`mp_discount_scope = product`). Until then `no_discount_fallback` decides: wait for sales (`""`, the WB default), use the account's median over 10+ orders (`account_median`, WB only — its SPP is much the same across a seller's cards) or keep `target_price` as the seller price (`seller_price`, the Ozon default since migration 0037) |
| `seller_price` | `target_price`: the price after the seller's discount |
| `margin` | break-even × (1 + `target_margin_percent`); needs a cost price |

Then, in order:

- clamped to `[min_price, max_price]` and never below the break-even price (when the cost
  price is known);
- moved by at most `max_step_pct` (default 10 %) of the current price per change, since WB and
  Ozon quarantine sharp changes (WB: a cut of more than a third needs confirmation);
- skipped when within 0.5 % (at least 1 ₽) of the current price;
- skipped when the catalogue snapshot is older than 6 h, and after a live change until the
  next catalogue snapshot shows the result.

WB receives the list price for the new seller price with the card's current discount; Ozon
receives the new price with the crossed-out price scaled by the same factor (Ozon reads
`old_price: 0` as "no discount").

## Ozon: what the buyer pays (findings of 2026-10-20)

Checked on the live account, in the seller cabinet and as a buyer on ozon.ru:

- **The discount is Ozon's "баллы за скидки", per card.** In the finance accruals
  `commission.bonus` is "Баллы за скидки": Ozon lowers the buyer price at its own expense and
  pays the seller the difference in points (1 pt = 1 ₽, spent on Ozon services);
  `sale_price` is what the buyer paid in money, `coinvestment` (~0.5 %) is "Программы
  партнёров". The share differs per card and changes over time: 45–55 % on old cards with
  sales, ~35 % on some of them right now, ~3 % on cards created a week earlier, 0 without
  sales. An account median says nothing about a card, so Ozon never uses it (migration 0036).
- **The current buyer price is not available to us.** `/v5/product/info/prices` gives
  `price`, `old_price`, `min_price` and `marketing_seller_price` (the seller's price with the
  seller's own promotions); `/v3/product/info/list` has no buyer price either.
  `/v1/product/prices/details` has it but is open only with the Premium PRO subscription
  (~25 000 ₽ a month), which the seller does not buy — it answers "no access to this method".
  ozon.ru shows an antibot captcha to an automated browser, so a buyer price is checked by
  hand, at checkout.
- **A median over past sales lags the current discount.** `pukly10klbr10black` measured 67 %
  on its 3 sales, so the repricer set 1171 ₽ for a desired 387 ₽; the buyer paid 758 ₽ at
  checkout (~35 %). The page's "Цена для покупателя" on Ozon is an estimate from history,
  not the shelf price.
- **Rule chosen by the seller:** an Ozon desired-price rule keeps the desired price as the
  seller's price until the card has 3 sales, then prices on the card's measured discount
  (`no_discount_fallback = seller_price`, default for new Ozon rules; migration 0037 moved the
  rules that waited for sales). On rollout 173 old cards whose manual prices were ~2× the
  desired price started stepping down to it; while Ozon still gives them points, buyers pay
  less than the desired price until 3 sales measure the discount.
- **From the first sale (2026-10-21):** after the rollout above, Ozon kept its ~50–70 %
  points on cards with 1–2 sales whose prices stepped down to the desired one, so buyers paid
  about half of it. An Ozon card's discount is its own even on one sale, so an Ozon rule now
  prices on it from the first sale (WB still needs 3 orders); only cards without sales keep the
  desired price as the seller's. Ozon's current discount is not visible to us, so the repricer
  learns of a new one only from the card's next sales — finance accruals arrive days after the
  order — and a figure from one old sale can be higher than what Ozon gives today.
- **Pace:** the catalogue snapshot is taken hourly (`:27`), and after a live change a rule
  waits for the next snapshot, so a card moves by `max_step_pct` (10 %) about once an hour; at
  most `MARKETPLACE_ACTIONS_MAX_PER_RUN` (100) prices are written per 10-minute run, the rest
  are `deferred` to the next runs.
- **The card's own `min_price` on Ozon** is not sent by the repricer. Whether Ozon accepts a
  price below it was not checked: the seller removed `min_price` (600 ₽) from the
  `btn25pgf051050*` cards whose desired price is ~400 ₽.
- **When a buyer cannot find or order a card,** look at stocks before prices: a card with no
  stock (`has_stock: false`) is not shown in search; a 404 at checkout of a card with FBO
  stock is a delivery/warehouse matter, not the price.

## Going live checklist

- Run the rule in dry-run for a few days and review `…/actions`.
- Configure the write tokens and a sane `MARKETPLACE_ACTIONS_MAX_PER_RUN`.
- Set `MARKETPLACE_ACTIONS_ENABLED=true` on the workers, then switch individual rules off dry-run.
- Emergency stop: set `MARKETPLACE_ACTIONS_ENABLED=false` and restart workers.
