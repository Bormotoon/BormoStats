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
| Price change | WB | `POST discounts-prices-api.wildberries.ru/api/v2/upload/task` (`nmID`, `price`) | `WB_TOKEN_PRICES` |
| Price change | Ozon | `POST api-seller.ozon.ru/v1/product/import/prices` | `OZON_CLIENT_ID` / `OZON_API_KEY` |
| Stock update | WB | `PUT marketplace-api.wildberries.ru/api/v3/stocks/{warehouseId}` (`chrtId`, `amount`) | `WB_TOKEN_MARKETPLACE` |
| Stock update | Ozon | `POST api-seller.ozon.ru/v2/products/stocks` (≤100 items per call) | `OZON_CLIENT_ID` / `OZON_API_KEY` |

Ozon Performance (ad bid) changes are not integrated yet and are recorded as
`unsupported`. A WB bid rule needs `product_id` (nm_id) and `placement`
(`combined` for unified-bid campaigns, `search`/`recommendations` for manual ones).

## Going live checklist

- Run the rule in dry-run for a few days and review `…/actions`.
- Configure the write tokens and a sane `MARKETPLACE_ACTIONS_MAX_PER_RUN`.
- Set `MARKETPLACE_ACTIONS_ENABLED=true` on the workers, then switch individual rules off dry-run.
- Emergency stop: set `MARKETPLACE_ACTIONS_ENABLED=false` and restart workers.
