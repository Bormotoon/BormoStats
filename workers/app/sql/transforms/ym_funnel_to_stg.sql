INSERT INTO stg_funnel_daily
(day, marketplace, account_id, product_id, nm_id, views, adds_to_cart, orders, orders_sum,
 buyouts, cancels, add_to_cart_conv, cart_to_order_conv, buyout_percent, wishlist, currency, meta_json, ingested_at)
WITH mappings AS
(
  SELECT account_id, offer_id, market_sku
  FROM raw_ym_offer_mappings FINAL
  WHERE market_sku > 0
)
SELECT f.day, 'ym', f.account_id,
  toString(if(m.market_sku > 0, m.market_sku, f.product_id)),
  if(m.market_sku > 0, m.market_sku, f.product_id), f.shows, f.to_cart, f.orders, f.revenue,
  f.orders, 0, if(f.shows > 0, toFloat64(f.to_cart) / f.shows, 0),
  if(f.to_cart > 0, toFloat64(f.orders) / to_cart, 0), 0, 0, 'RUB', '', f.ingested_at
FROM raw_ym_funnel AS f FINAL
LEFT JOIN mappings AS m ON m.account_id = f.account_id AND m.offer_id = f.offer_id
WHERE f.day >= toDate(now(), 'Europe/Moscow') - %(days)s;
