-- Current price breakdown per product card (marketplace x account x supplier article), rebuilt
-- whole on every run; rows of an earlier build are deleted after the insert (see marts.py).
--
-- Seller side comes from the latest catalogue snapshot in the history store:
--   WB    price.sizes[1].price (list price), price.discount (percent), sizes[1].discountedPrice
--   Ozon  price.price.old_price (list price, 0 = none), price.price.price, commissions, acquiring
-- The marketplace's own discount (WB SPP and wallet, Ozon co-financed discounts and points) is
-- not in the price APIs, so it is measured on recent sales, as a median per product:
--   WB    1 - finishedPrice / priceWithDisc over orders (raw_wb_orders), not cancelled
--   Ozon  1 - sale_price / seller_price over sale accruals (raw_ozon_finance_ops)
-- The last 7 (WB) / 14 (Ozon) days are used when they hold 3+ sales, else 30 / 60 days. On WB
-- a product with fewer than 3 orders gets the account's median (mp_discount_scope = 'account',
-- an estimate), since WB's SPP is much the same across a seller's cards. Ozon's discount is
-- left empty for a product without its own sales: it is mostly Ozon's "баллы за скидки", which
-- Ozon gives per card (from 0 to ~55% on one account; new cards get next to none), so the
-- account's median says nothing about such a card. mp_discount_samples counts the sales behind
-- the value (the account's for an account median).
--
-- Fees per unit at the current seller price:
--   commission_pct  WB: (commission + acquiring) / sales of the product over 60 days of the
--                   realization report (account-wide when the product has no sales);
--                   Ozon: the current tariff of the card for the account's scheme (FBO/FBS)
--   acquiring_rub   Ozon: the card's acquiring in roubles; WB: in commission_pct
--   logistics_rub   delivery and reverse logistics per sold unit over 60 days (account-wide
--                   fallback; Ozon falls back to the card's tariff)
-- margin_rub = seller_price - fees - cost; break-even is the seller price with zero margin.
-- Cost price: dim_offer_cost by supplier article, else the legacy dim_product_cost.
INSERT INTO mrt_price_current
(
  marketplace, account_id, offer_id, product_id, ozon_product_id, title, image_url,
  list_price, seller_discount_pct, seller_price,
  mp_discount_pct, mp_discount_scope, mp_discount_samples, buyer_price,
  commission_pct, commission_rub, acquiring_rub, logistics_rub, fees_rub,
  cost_price, margin_rub, margin_pct, breakeven_price,
  min_price, auto_actions_enabled, price_seen_at, built_at
)
WITH
  {built_at:DateTime} AS build_ts,
  heads AS
  (
    SELECT r.marketplace AS marketplace, r.account_id AS account_id, o.body AS body
    FROM hist_refs AS r FINAL
    INNER JOIN hist_objects AS o FINAL ON o.object_hash = r.head_object
    WHERE r.repo = 'product' AND r.is_deleted = 0
  ),
  seen AS
  (
    SELECT
      maxIf(finished_at, task_name = 'tasks.history.wb_catalog_snapshot') AS wb_seen,
      maxIf(finished_at, task_name = 'tasks.history.ozon_catalog_snapshot') AS ozon_seen
    FROM sys_task_runs
    WHERE status = 'success'
      AND task_name IN ('tasks.history.wb_catalog_snapshot', 'tasks.history.ozon_catalog_snapshot')
  ),
  wb_cards AS
  (
    SELECT
      account_id,
      toString(JSONExtractUInt(body, 'card', 'nmID')) AS product_id,
      JSONExtractString(body, 'card', 'vendorCode') AS offer_id,
      JSONExtractFloat(body, 'price', 'sizes', 1, 'price') AS list_price,
      JSONExtractFloat(body, 'price', 'discount') AS seller_discount_pct,
      JSONExtractFloat(body, 'price', 'sizes', 1, 'discountedPrice') AS seller_price
    FROM heads
    WHERE marketplace = 'wb' AND JSONLength(body, 'price', 'sizes') > 0
  ),
  wb_orders AS
  (
    SELECT
      account_id,
      toString(nm_id) AS product_id,
      event_ts >= now() - toIntervalDay(7) AS recent,
      (1 - JSONExtractFloat(payload, 'finishedPrice') / JSONExtractFloat(payload, 'priceWithDisc'))
        * 100 AS discount_pct
    FROM raw_wb_orders FINAL
    WHERE event_ts >= now() - toIntervalDay(30)
      AND NOT JSONExtractBool(payload, 'isCancel')
      AND JSONExtractFloat(payload, 'priceWithDisc') > 0
      AND JSONExtractFloat(payload, 'finishedPrice') > 0
  ),
  wb_discount AS
  (
    SELECT
      account_id,
      product_id,
      if(countIf(recent) >= 3, countIf(recent), count()) AS samples,
      if(countIf(recent) >= 3, quantileExactIf(0.5)(discount_pct, recent),
        quantileExact(0.5)(discount_pct)) AS discount_pct
    FROM wb_orders
    GROUP BY account_id, product_id
  ),
  wb_discount_account AS
  (
    SELECT
      account_id,
      if(countIf(recent) >= 10, countIf(recent), count()) AS samples,
      if(countIf(recent) >= 10, quantileExactIf(0.5)(discount_pct, recent),
        quantileExact(0.5)(discount_pct)) AS discount_pct
    FROM wb_orders
    GROUP BY account_id
  ),
  wb_report AS
  (
    SELECT
      account_id,
      toString(nm_id) AS product_id,
      sumIf(sales, sales > 0) AS sales_sum,
      -sum(commission) - sum(acquiring) AS commission_sum,
      -sum(logistics) - sum(reverse_logistics) AS logistics_sum,
      sumIf(quantity, doc_type = 'Продажа' AND sales > 0) AS units
    FROM raw_wb_sales_report FINAL
    WHERE day >= today() - 60 AND nm_id > 0
    GROUP BY account_id, nm_id
  ),
  wb_report_account AS
  (
    SELECT
      account_id,
      sum(sales_sum) AS sales_sum,
      sum(commission_sum) AS commission_sum,
      sum(logistics_sum) AS logistics_sum,
      sum(units) AS units
    FROM wb_report
    GROUP BY account_id
  ),
  ozon_cards AS
  (
    SELECT
      account_id,
      toString(JSONExtractUInt(body, 'info', 'sku')) AS product_id,
      JSONExtractUInt(body, 'info', 'id') AS ozon_product_id,
      JSONExtractString(body, 'info', 'offer_id') AS offer_id,
      JSONExtractFloat(body, 'price', 'price', 'old_price') AS old_price,
      JSONExtractFloat(body, 'price', 'price', 'price') AS seller_price,
      JSONExtractFloat(body, 'price', 'price', 'min_price') AS min_price,
      JSONExtractBool(body, 'price', 'price', 'auto_action_enabled') AS auto_actions_enabled,
      JSONExtractFloat(body, 'price', 'commissions', 'sales_percent_fbo') AS pct_fbo,
      JSONExtractFloat(body, 'price', 'commissions', 'sales_percent_fbs') AS pct_fbs,
      JSONExtractFloat(body, 'price', 'acquiring') AS acquiring_rub,
      JSONExtractFloat(body, 'price', 'commissions', 'fbo_direct_flow_trans_min_amount')
        + JSONExtractFloat(body, 'price', 'commissions', 'fbo_deliv_to_customer_amount')
        AS tariff_logistics_fbo,
      JSONExtractFloat(body, 'price', 'commissions', 'fbs_direct_flow_trans_min_amount')
        + JSONExtractFloat(body, 'price', 'commissions', 'fbs_deliv_to_customer_amount')
        AS tariff_logistics_fbs
    FROM heads
    WHERE marketplace = 'ozon' AND JSONExtractFloat(body, 'price', 'price', 'price') > 0
  ),
  -- one row per product line of a sale accrual; amounts are strings ("623")
  ozon_lines AS
  (
    SELECT
      account_id,
      operation_ts >= now() - toIntervalDay(14) AS recent,
      JSONExtractString(payload, 'posting', 'delivery_schema') AS scheme,
      toString(JSONExtractUInt(line, 'sku')) AS product_id,
      greatest(JSONExtractUInt(line, 'quantity'), 1) AS qty,
      toFloat64OrZero(JSONExtractString(line, 'commission', 'seller_price', 'amount'))
        AS seller_price,
      toFloat64OrZero(JSONExtractString(line, 'commission', 'sale_price', 'amount'))
        AS sale_price,
      -toFloat64OrZero(JSONExtractString(line, 'delivery', 'total_accrued', 'amount'))
        AS delivery_rub
    FROM raw_ozon_finance_ops FINAL
    ARRAY JOIN JSONExtractArrayRaw(payload, 'posting', 'products') AS line
    WHERE type = 'posting' AND operation_ts >= now() - toIntervalDay(60)
  ),
  ozon_sales AS
  (
    SELECT * FROM ozon_lines WHERE seller_price > 0 AND sale_price > 0
  ),
  ozon_discount AS
  (
    SELECT
      account_id,
      product_id,
      if(countIf(recent) >= 3, countIf(recent), count()) AS samples,
      if(countIf(recent) >= 3,
        quantileExactIf(0.5)((1 - sale_price / seller_price) * 100, recent),
        quantileExact(0.5)((1 - sale_price / seller_price) * 100)) AS discount_pct,
      sumIf(delivery_rub, delivery_rub > 0) AS delivery_sum,
      sumIf(qty, delivery_rub > 0) AS delivery_units
    FROM ozon_sales
    GROUP BY account_id, product_id
  ),
  ozon_account AS
  (
    SELECT
      account_id,
      countIf(scheme = 'Fbs') > countIf(scheme = 'Fbo') AS is_fbs,
      sumIf(delivery_rub, delivery_rub > 0) AS delivery_sum,
      sumIf(qty, delivery_rub > 0) AS delivery_units
    FROM ozon_sales
    GROUP BY account_id
  ),
  costs AS
  (
    SELECT a.marketplace AS marketplace, a.account_id AS account_id, c.offer_id AS offer_id,
      c.cost_price_rub AS cost_price
    FROM (SELECT marketplace, account_id, organization_id FROM dim_account FINAL) AS a
    INNER JOIN (SELECT organization_id, offer_id, cost_price_rub FROM dim_offer_cost FINAL) AS c
      ON c.organization_id = a.organization_id
  ),
  legacy_costs AS
  (
    SELECT marketplace, toString(product_id) AS product_id, cost_price_rub AS cost_price
    FROM dim_product_cost FINAL
  ),
  products AS
  (
    SELECT marketplace, account_id, product_id, anyLast(title) AS title,
      anyLast(image_url) AS image_url
    FROM dim_product FINAL
    GROUP BY marketplace, account_id, product_id
  ),
  priced AS
  (
    SELECT
      'wb' AS marketplace,
      c.account_id AS account_id,
      c.offer_id AS offer_id,
      c.product_id AS product_id,
      CAST(NULL, 'Nullable(UInt64)') AS ozon_product_id,
      c.list_price AS list_price,
      c.seller_discount_pct AS seller_discount_pct,
      c.seller_price AS seller_price,
      if(d.samples >= 3, d.discount_pct, da.discount_pct) AS mp_discount_pct,
      multiIf(d.samples >= 3, 'product', da.discount_pct IS NOT NULL, 'account', '')
        AS mp_discount_scope,
      toUInt32(if(d.samples >= 3, d.samples, ifNull(da.samples, 0))) AS mp_discount_samples,
      if(rp.units > 0 AND rp.sales_sum > 0, rp.commission_sum / rp.sales_sum,
        if(ra.sales_sum > 0, ra.commission_sum / ra.sales_sum, 0)) * 100 AS commission_pct,
      0. AS acquiring_rub,
      if(rp.units > 0 AND rp.logistics_sum > 0, rp.logistics_sum / rp.units,
        if(ra.units > 0, ra.logistics_sum / ra.units, 0)) AS logistics_rub,
      CAST(NULL, 'Nullable(Float64)') AS min_price,
      CAST(NULL, 'Nullable(UInt8)') AS auto_actions_enabled,
      (SELECT wb_seen FROM seen) AS price_seen_at
    FROM wb_cards AS c
    LEFT JOIN wb_discount AS d ON d.account_id = c.account_id AND d.product_id = c.product_id
    LEFT JOIN wb_discount_account AS da ON da.account_id = c.account_id
    LEFT JOIN wb_report AS rp ON rp.account_id = c.account_id AND rp.product_id = c.product_id
    LEFT JOIN wb_report_account AS ra ON ra.account_id = c.account_id

    UNION ALL

    SELECT
      'ozon' AS marketplace,
      c.account_id AS account_id,
      c.offer_id AS offer_id,
      c.product_id AS product_id,
      CAST(c.ozon_product_id, 'Nullable(UInt64)') AS ozon_product_id,
      if(c.old_price > c.seller_price, c.old_price, c.seller_price) AS list_price,
      if(c.old_price > c.seller_price, (1 - c.seller_price / c.old_price) * 100, 0)
        AS seller_discount_pct,
      c.seller_price AS seller_price,
      if(d.samples > 0, d.discount_pct, NULL) AS mp_discount_pct,
      if(d.samples > 0, 'product', '') AS mp_discount_scope,
      toUInt32(ifNull(d.samples, 0)) AS mp_discount_samples,
      if(ifNull(oa.is_fbs, 0), c.pct_fbs, c.pct_fbo) AS commission_pct,
      c.acquiring_rub AS acquiring_rub,
      if(d.delivery_units > 0, d.delivery_sum / d.delivery_units,
        if(oa.delivery_units > 0, oa.delivery_sum / oa.delivery_units,
          if(ifNull(oa.is_fbs, 0), c.tariff_logistics_fbs, c.tariff_logistics_fbo)))
        AS logistics_rub,
      CAST(c.min_price, 'Nullable(Float64)') AS min_price,
      CAST(c.auto_actions_enabled, 'Nullable(UInt8)') AS auto_actions_enabled,
      (SELECT ozon_seen FROM seen) AS price_seen_at
    FROM ozon_cards AS c
    LEFT JOIN ozon_discount AS d ON d.account_id = c.account_id AND d.product_id = c.product_id
    LEFT JOIN ozon_account AS oa ON oa.account_id = c.account_id
  )
SELECT
  p.marketplace AS marketplace,
  p.account_id AS account_id,
  p.offer_id AS offer_id,
  p.product_id AS product_id,
  p.ozon_product_id AS ozon_product_id,
  i.title AS title,
  i.image_url AS image_url,
  round(p.list_price, 2) AS list_price,
  round(p.seller_discount_pct, 2) AS seller_discount_pct,
  round(p.seller_price, 2) AS seller_price,
  round(p.mp_discount_pct, 2) AS mp_discount_pct,
  p.mp_discount_scope AS mp_discount_scope,
  p.mp_discount_samples AS mp_discount_samples,
  round(p.seller_price * (1 - p.mp_discount_pct / 100), 2) AS buyer_price,
  round(p.commission_pct, 2) AS commission_pct,
  round(p.seller_price * p.commission_pct / 100, 2) AS commission_rub,
  round(p.acquiring_rub, 2) AS acquiring_rub,
  round(p.logistics_rub, 2) AS logistics_rub,
  round(commission_rub + acquiring_rub + logistics_rub, 2) AS fees_rub,
  if(ifNull(k.cost_price, 0) > 0, k.cost_price,
    if(ifNull(l.cost_price, 0) > 0, l.cost_price, NULL)) AS cost_price,
  round(seller_price - fees_rub - cost_price, 2) AS margin_rub,
  round(if(seller_price > 0, margin_rub / seller_price * 100, NULL), 2) AS margin_pct,
  round(if(commission_pct < 100,
    (cost_price + acquiring_rub + logistics_rub) / (1 - commission_pct / 100), NULL), 2)
    AS breakeven_price,
  p.min_price AS min_price,
  p.auto_actions_enabled AS auto_actions_enabled,
  p.price_seen_at AS price_seen_at,
  build_ts AS built_at
FROM priced AS p
LEFT JOIN products AS i
  ON i.marketplace = p.marketplace AND i.account_id = p.account_id AND i.product_id = p.product_id
LEFT JOIN costs AS k
  ON k.marketplace = p.marketplace AND k.account_id = p.account_id AND k.offer_id = p.offer_id
LEFT JOIN legacy_costs AS l ON l.marketplace = p.marketplace AND l.product_id = p.product_id
WHERE p.offer_id != '' AND p.seller_price > 0
SETTINGS join_use_nulls = 1
