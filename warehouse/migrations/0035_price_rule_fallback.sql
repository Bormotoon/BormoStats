-- What a 'buyer_price' rule does while the marketplace's discount for its card cannot be
-- measured (too few of the card's own sales, see workers/app/tasks/repricer.py):
--   ''               wait for sales and leave the price alone (the default)
--   'account_median' compute the seller price with the account's median discount
--   'seller_price'   keep target_price as the seller's price until the discount is measured
ALTER TABLE dim_price_rule ADD COLUMN IF NOT EXISTS no_discount_fallback LowCardinality(String) DEFAULT '';
