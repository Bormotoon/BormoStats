INSERT INTO stg_sales
(event_ts, marketplace, account_id, order_id, posting_number, srid, product_id, nm_id, ozon_product_id,
 offer_id, qty, price_gross, payout, is_return, last_change_ts, meta_json, ingested_at)
SELECT updated_at, 'ym', account_id, toString(order_id), NULL, NULL, toString(product_id), product_id,
  NULL, offer_id,
  if(status IN ('RETURNED'), -toInt32(qty), toInt32(qty)),
  seller_price, if(status = 'RETURNED', -seller_price * qty, seller_price * qty), toUInt8(status IN ('RETURNED')),
  updated_at, payload, ingested_at
FROM raw_ym_orders FINAL
WHERE updated_at >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(updated_at, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
  AND status IN ('DELIVERED', 'RETURNED');
