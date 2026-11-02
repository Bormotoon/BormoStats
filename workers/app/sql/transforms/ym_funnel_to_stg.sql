INSERT INTO stg_funnel_daily
(day, marketplace, account_id, product_id, nm_id, views, adds_to_cart, orders, orders_sum,
 buyouts, cancels, add_to_cart_conv, cart_to_order_conv, buyout_percent, wishlist, currency, meta_json, ingested_at)
SELECT day, 'ym', account_id, toString(product_id), product_id, shows, to_cart, orders, revenue,
  orders, 0, if(shows > 0, toFloat64(to_cart) / shows, 0),
  if(to_cart > 0, toFloat64(orders) / to_cart, 0), 0, 0, 'RUB', '', ingested_at
FROM raw_ym_funnel FINAL
WHERE day >= today() - %(days)s;
