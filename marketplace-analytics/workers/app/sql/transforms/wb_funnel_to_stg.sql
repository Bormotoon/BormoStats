INSERT INTO stg_funnel_daily
(
  day,
  marketplace,
  account_id,
  product_id,
  nm_id,
  views,
  adds_to_cart,
  orders,
  orders_sum,
  buyouts,
  cancels,
  add_to_cart_conv,
  cart_to_order_conv,
  buyout_percent,
  wishlist,
  currency,
  meta_json,
  ingested_at
)
SELECT
  day,
  'wb' AS marketplace,
  account_id,
  toString(nm_id) AS product_id,
  nm_id,
  open_card_count AS views,
  add_to_cart_count AS adds_to_cart,
  orders_count AS orders,
  orders_sum_rub AS orders_sum,
  buyouts_count AS buyouts,
  cancel_count AS cancels,
  add_to_cart_conv,
  cart_to_order_conv,
  buyout_percent,
  add_to_wishlist AS wishlist,
  currency,
  payload AS meta_json,
  ingested_at
FROM raw_wb_funnel_daily FINAL
WHERE day >= today() - %(days)s
