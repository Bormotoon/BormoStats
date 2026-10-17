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
| `buyer_price` | `target_price / (1 − marketplace discount)`: keeps what the buyer pays after WB SPP or Ozon's co-financed discounts. Acts on a discount measured on **3+ of the card's own sales** (`mp_discount_scope = product`); on WB, whose SPP is much the same across a seller's cards, also on the account's median over 10+ orders (`account`). Ozon's discounts vary between cards (14–70 % on real data), so its account median is shown but not acted upon |
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

## Going live checklist

- Run the rule in dry-run for a few days and review `…/actions`.
- Configure the write tokens and a sane `MARKETPLACE_ACTIONS_MAX_PER_RUN`.
- Set `MARKETPLACE_ACTIONS_ENABLED=true` on the workers, then switch individual rules off dry-run.
- Emergency stop: set `MARKETPLACE_ACTIONS_ENABLED=false` and restart workers.
