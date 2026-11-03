INSERT INTO dim_product
(marketplace, account_id, product_id, nm_id, chrt_id, sku, offer_id, ozon_product_id,
 title, brand, category, image_url, updated_at)
SELECT 'ym', account_id, toString(if(market_sku > 0, market_sku, cityHash64(offer_id))),
 NULL, NULL, offer_id, offer_id, NULL,
 nullIf(name, ''),
 nullIf(
   if(
     JSONExtractString(payload, 'offer', 'vendor') != '',
     JSONExtractString(payload, 'offer', 'vendor'),
     JSONExtractString(payload, 'mapping', 'market', 'vendor', 'name')
   ),
   ''
 ),
 nullIf(
   if(
     JSONExtractString(payload, 'mapping', 'marketCategoryName') != '',
     JSONExtractString(payload, 'mapping', 'marketCategoryName'),
     JSONExtractString(payload, 'mapping', 'market', 'marketCategoryName')
   ),
   ''
 ),
 nullIf(pictures[1], ''), now()
FROM raw_ym_offer_mappings FINAL;
