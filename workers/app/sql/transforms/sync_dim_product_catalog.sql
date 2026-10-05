-- Product dictionary from the catalogue in the history store (repo `product`): every card of the
-- seller with title, brand and category, sold or not. Runs after the sales-based syncs, so on the
-- same key (product_id, chrt_id) the card wins. WB: one row per size, product_id = nmID, offer_id =
-- vendorCode, category = subjectName. Ozon: product_id = SKU (the id marts use), ozon_product_id =
-- product id, brand from attribute 85; no category (cards carry only type_id; ponytail: names need
-- /v1/description-category/tree).
-- image_url: the card's first photo as a thumbnail (WB c246x328, Ozon primary_image).
INSERT INTO dim_product
(
  marketplace,
  account_id,
  product_id,
  nm_id,
  chrt_id,
  sku,
  offer_id,
  ozon_product_id,
  title,
  brand,
  category,
  image_url,
  updated_at
)
WITH cards AS
(
  SELECT r.marketplace AS marketplace, r.account_id AS account_id, o.body AS body
  FROM hist_refs AS r FINAL
  INNER JOIN hist_objects AS o FINAL ON o.object_hash = r.head_object
  WHERE r.repo = 'product' AND r.is_deleted = 0
)
SELECT
  'wb' AS marketplace,
  account_id,
  toString(JSONExtractUInt(body, 'card', 'nmID')) AS product_id,
  JSONExtractUInt(body, 'card', 'nmID') AS nm_id,
  JSONExtractUInt(size, 'chrtID') AS chrt_id,
  JSONExtractString(size, 'skus', 1) AS sku,
  JSONExtractString(body, 'card', 'vendorCode') AS offer_id,
  NULL AS ozon_product_id,
  nullIf(JSONExtractString(body, 'card', 'title'), '') AS title,
  nullIf(JSONExtractString(body, 'card', 'brand'), '') AS brand,
  nullIf(JSONExtractString(body, 'card', 'subjectName'), '') AS category,
  nullIf(JSONExtractString(body, 'card', 'photos', 1, 'c246x328'), '') AS image_url,
  now() AS updated_at
FROM cards
ARRAY JOIN JSONExtractArrayRaw(body, 'card', 'sizes') AS size
WHERE marketplace = 'wb' AND JSONExtractUInt(body, 'card', 'nmID') > 0

UNION ALL

SELECT
  'ozon' AS marketplace,
  account_id,
  toString(JSONExtractUInt(body, 'info', 'sku')) AS product_id,
  NULL AS nm_id,
  NULL AS chrt_id,
  JSONExtractString(body, 'info', 'offer_id') AS sku,
  JSONExtractString(body, 'info', 'offer_id') AS offer_id,
  JSONExtractUInt(body, 'info', 'id') AS ozon_product_id,
  nullIf(JSONExtractString(body, 'info', 'name'), '') AS title,
  nullIf(
    JSONExtractString(
      arrayFirst(
        a -> JSONExtractUInt(a, 'id') = 85,
        JSONExtractArrayRaw(body, 'attributes', 'attributes')
      ),
      'values', 1, 'value'
    ),
    ''
  ) AS brand,
  NULL AS category,
  nullIf(
    if(
      JSONLength(body, 'info', 'primary_image') > 0,
      JSONExtractString(body, 'info', 'primary_image', 1),
      JSONExtractString(body, 'info', 'images', 1)
    ),
    ''
  ) AS image_url,
  now() AS updated_at
FROM cards
WHERE marketplace = 'ozon' AND JSONExtractUInt(body, 'info', 'sku') > 0
