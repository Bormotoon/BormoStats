INSERT INTO dim_product
(marketplace, account_id, product_id, nm_id, chrt_id, sku, offer_id, ozon_product_id,
 title, brand, category, image_url, updated_at)
SELECT 'ym', account_id, toString(if(market_sku > 0, market_sku, cityHash64(offer_id))),
 NULL, NULL, offer_id, offer_id, NULL, name, NULL, NULL, nullIf(pictures[1], ''), now()
FROM raw_ym_offer_mappings FINAL;
