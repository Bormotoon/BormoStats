INSERT INTO stg_stocks
(snapshot_ts, marketplace, account_id, product_id, nm_id, ozon_product_id, offer_id, warehouse_id,
 amount, reserved, present, meta_json, ingested_at)
WITH mappings AS
(
  SELECT account_id, offer_id, market_sku
  FROM raw_ym_offer_mappings FINAL
  WHERE market_sku > 0
)
SELECT s.snapshot_ts, 'ym', s.account_id,
  toString(if(m.market_sku > 0, m.market_sku, s.product_id)),
  if(m.market_sku > 0, m.market_sku, s.product_id), NULL, s.offer_id,
  toUInt64(s.warehouse_id), toInt32(s.stock_fit), toInt32(s.stock_freeze), toInt32(s.stock_fit), s.payload, now()
FROM raw_ym_stocks AS s FINAL
LEFT JOIN mappings AS m ON m.account_id = s.account_id AND m.offer_id = s.offer_id
WHERE s.snapshot_ts >= now() - toIntervalDay(%(days)s + 2);
