-- Ozon gives its discount ("баллы за скидки") per card, so a desired-price rule on a card with
-- fewer than 3 sales cannot be priced on a measured discount. Instead of waiting for sales it
-- keeps the desired price as the seller's price meanwhile; from the 3rd sale the repricer prices
-- it on the card's own discount (workers/app/tasks/repricer.py). New Ozon rules get it too.
ALTER TABLE dim_price_rule UPDATE no_discount_fallback = 'seller_price'
WHERE marketplace = 'ozon' AND no_discount_fallback = ''
  SETTINGS mutations_sync = 2;
