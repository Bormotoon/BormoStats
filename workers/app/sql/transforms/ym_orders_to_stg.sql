INSERT INTO stg_orders
(event_ts, marketplace, account_id, order_id, status, product_id, qty, price_gross, last_change_ts, meta_json, ingested_at)
SELECT created_at, 'ym', account_id, toString(order_id), lower(status), toString(product_id),
  toInt32(qty), seller_price, updated_at, payload, ingested_at
FROM raw_ym_orders FINAL
WHERE created_at >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(created_at, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s;
