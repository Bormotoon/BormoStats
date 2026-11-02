INSERT INTO stg_stocks
(snapshot_ts, marketplace, account_id, product_id, nm_id, ozon_product_id, offer_id, warehouse_id,
 amount, reserved, present, meta_json, ingested_at)
SELECT snapshot_ts, 'ym', account_id, toString(product_id), product_id, NULL, offer_id,
  toUInt64(warehouse_id), toInt32(stock_fit), toInt32(stock_freeze), toInt32(stock_fit), payload, now()
FROM raw_ym_stocks FINAL
WHERE snapshot_ts >= now() - toIntervalDay(%(days)s + 2);
