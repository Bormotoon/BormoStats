INSERT INTO stg_orders
(event_ts, marketplace, account_id, order_id, status, product_id, qty, price_gross, last_change_ts, meta_json, ingested_at)
WITH mappings AS
(
  SELECT account_id, offer_id, market_sku
  FROM raw_ym_offer_mappings FINAL
  WHERE market_sku > 0
)
SELECT o.created_at, 'ym', o.account_id, toString(o.order_id), lower(o.status),
  toString(if(m.market_sku > 0, m.market_sku, o.product_id)),
  toInt32(o.qty), o.seller_price, o.updated_at, o.payload, o.ingested_at
FROM raw_ym_orders AS o FINAL
LEFT JOIN mappings AS m ON m.account_id = o.account_id AND m.offer_id = o.offer_id
WHERE o.created_at >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(o.created_at, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s;
