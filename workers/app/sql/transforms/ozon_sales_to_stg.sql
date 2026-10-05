-- Ozon sales are the realization accruals (/v1/finance/accrual/by-day, category POSTING),
-- not the posting list: a posting stays "delivered" after the buyer returns it, cancelled
-- postings never sold, and the posting date is the order date, not the day of the sale.
-- A POSTING accrual whose product carries a commission block is a sale (sale_amount > 0)
-- or its reversal for a return (sale_amount < 0); accruals without it are later
-- logistics charges and belong to the P&L, not to sales.
--   qty          units, negative for a return
--   price_gross  seller's price per unit (commission.seller_price basis), positive
--   payout       sale_amount + commission: amount due before logistics, as WB forPay
-- One stg row per (accrual, SKU); the accrual date is a Moscow day.
INSERT INTO stg_sales
(
  event_ts,
  marketplace,
  account_id,
  order_id,
  posting_number,
  srid,
  product_id,
  nm_id,
  ozon_product_id,
  offer_id,
  qty,
  price_gross,
  payout,
  is_return,
  last_change_ts,
  meta_json,
  ingested_at
)
SELECT
  toDateTime(accrual_day, 'Europe/Moscow') AS event_ts,
  'ozon' AS marketplace,
  account_id,
  operation_id AS order_id,
  nullIf(JSONExtractString(payload, 'unit_number'), '') AS posting_number,
  NULL AS srid,
  toString(sku) AS product_id,
  NULL AS nm_id,
  sku AS ozon_product_id,
  NULL AS offer_id,
  toInt32(if(sale_amount < 0, -quantity, quantity)) AS qty,
  abs(sale_amount) / quantity AS price_gross,
  sale_amount + commission AS payout,
  if(sale_amount < 0, 1, 0) AS is_return,
  NULL AS last_change_ts,
  product AS meta_json,
  ingested_at
FROM
(
  SELECT
    account_id,
    operation_id,
    payload,
    ingested_at,
    toDate(JSONExtractString(payload, 'date')) AS accrual_day,
    arrayJoin(JSONExtractArrayRaw(JSONExtractRaw(payload, 'posting'), 'products')) AS product,
    JSONExtractUInt(product, 'sku') AS sku,
    toInt64(greatest(JSONExtractUInt(product, 'quantity'), 1)) AS quantity,
    toFloat64OrZero(JSONExtractString(product, 'commission', 'sale_amount', 'amount')) AS sale_amount,
    toFloat64OrZero(JSONExtractString(product, 'commission', 'commission', 'amount')) AS commission
  FROM raw_ozon_finance_ops FINAL
  WHERE source = 'accrual_by_day'
    AND JSONExtractString(payload, 'accrued_category') = 'POSTING'
    AND operation_ts >= now() - toIntervalDay(%(days)s + 2)
)
WHERE sale_amount != 0
  AND sku != 0
  AND accrual_day >= toDate(now(), 'Europe/Moscow') - %(days)s
