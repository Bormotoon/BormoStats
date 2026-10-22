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
| Price change | Ozon | `POST api-seller.ozon.ru/v1/product/import/prices` (`price`, `old_price` scaled with it, `min_price` = `price`) | `OZON_CLIENT_ID` / `OZON_API_KEY` |
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
`old_price: 0` as "no discount") and its limit price at the new price (see below).

## Ozon: the price index holds a buyer-price rule back (since 2026-10-22)

`/v5/product/info/prices` rates every card's price against the same item elsewhere
(`price_indexes`: `color_index` SUPER / GREEN / YELLOW / RED / WITHOUT_INDEX, and per source the
index value and the minimal price there; `self_marketplaces_index_data` is the seller's own price
on other marketplaces, i.e. WB). The catalogue snapshot keeps it, and `mrt_price_current` carries
the colour in `price_index_color` (migration 0038).

Found on 2026-10-22: the repricer raised Ozon cards to make up for the ~56 % discount measured
on their past sales, and Ozon answered by cutting its points. `btn204pgf10tplros`: desired
411 ₽, discount 56.6 % measured on sales at 520 ₽, raised to 947 ₽; the shelf showed 688 ₽
(619 ₽ with Ozon's bank) — 27 % off — and the card had no sales since. Of the 103 cards the
repricer had raised, 55 were RED (index ~1.4 against the seller's WB price); none of the
lowered ones were. The index follows a price change within the hour (`btn12pgf20d14flowerred`:
762 → 838 → 908 ₽ moved it 1.17 → 1.25 → 1.33); 1.03–1.05 is YELLOW, from ~1.06 RED. It is no
measure of the shelf price: 1.42 × 360 ₽ = 511 ₽ while the shelf showed 688 ₽.

So for a `buyer_price` rule on Ozon:

- **RED** — the price goes one `max_step_pct` step down from the current one per catalogue
  snapshot (lower if the rule itself asks for less), never below `target_price`: at that seller
  price the buyer pays the desired price even without Ozon's points; `[min_price, max_price]`
  and break-even still apply;
- **YELLOW** — the price is not raised (it may go down), so the card does not swing between
  GREEN and RED;
- other colours and WB — as before. `seller_price` and `margin` rules ignore the index.

The run's stats count `index_red` / `index_yellow`; the prices page shows "индекс цены Ozon
красный — снижаем" / "жёлтый — не поднимаем" instead of "держится на площадке".

## Ozon: the limit price and promotions (since 2026-10-22)

Since October 2026 Ozon has one **"предельная цена"** (limit price) per card for prices and
Ozon promotions; a card can no longer simply be taken out of a promotion. In the API it is
`min_price` of `/v1/product/import/prices` and `/v5/product/info/prices` (the cabinet's
"Предельная цена / Ограничение для акций"). A promotion gives each card a price for taking part
— `max_action_price` in `/v1/actions/products` and `/v1/actions/candidates`; for "Эластичный
бустинг" it is `price_min_elastic`, the cabinet's "Цена для минимального бустинга". The card
takes part while its limit is not above that price and leaves the promotion once the limit is
raised above it.

The repricer therefore keeps the limit of every Ozon card it prices **at the price it sets**:

- a price change sends `min_price` equal to the new price;
- a card whose price is within tolerance but whose limit is lower (by more than 0.5 %, at
  least 1 ₽) gets a `price_limit` action: the same price and crossed-out price, `min_price`
  raised to the price (`before_value`/`after_value` in the audit are the old and new limit);
- a rule that waits for the card's discount (no decision) leaves the limit alone; WB has no
  limit price.

So a promotion that asks for a lower price than the rule's never gets the card, and the card
leaves those it is in; a promotion whose price for taking part is at or above the rule's price
keeps it at the rule's own price — boosting without a discount. At rollout 162 of 270 live
Ozon rules had the limit below the price, by 43 % on average (`btn14pgf10grg`: price 1519 ₽,
limit 900 ₽), so promotions could sell those cards at about half the rule's price.

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
  not the shelf price. Raising the price makes it worse: Ozon cuts its points when the price
  index goes RED (see above).
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
- **The card's own `min_price` on Ozon** is the limit price above: since 2026-10-22 the
  repricer sets it to the price it keeps (108 cards already had it equal to the price, so
  Ozon accepts that).
- **When a buyer cannot find or order a card,** look at stocks before prices: a card with no
  stock (`has_stock: false`) is not shown in search; a 404 at checkout of a card with FBO
  stock is a delivery/warehouse matter, not the price.

## Going live checklist

- Run the rule in dry-run for a few days and review `…/actions`.
- Configure the write tokens and a sane `MARKETPLACE_ACTIONS_MAX_PER_RUN`.
- Set `MARKETPLACE_ACTIONS_ENABLED=true` on the workers, then switch individual rules off dry-run.
- Emergency stop: set `MARKETPLACE_ACTIONS_ENABLED=false` and restart workers.
