-- Ozon's discount is mostly its "баллы за скидки", given per card (new cards get next to none),
-- so the account's median discount says nothing about an Ozon card without sales: such a
-- 'buyer_price' rule keeps its target as the seller price instead (workers/app/tasks/repricer.py).
ALTER TABLE dim_price_rule UPDATE no_discount_fallback = 'seller_price'
WHERE marketplace = 'ozon' AND no_discount_fallback = 'account_median'
  SETTINGS mutations_sync = 2;
