-- Per Moscow day and product, net of returns (stg_sales holds returns with a negative qty):
--   revenue_rub     sales minus returns at the seller's price
--   payout_rub      amount due before logistics, sales minus return reversals
--   total_cost_rub  cost price x units kept by buyers (a returned unit goes back to stock)
--   profit_rub      payout_rub - total_cost_rub (logistics, storage and ads are P&L items)
--   margin_pct      profit_rub / revenue_rub
--   quantity        units sold; return_qty units returned (both positive)
INSERT INTO mrt_profit_daily
SELECT
    s.day,
    s.marketplace,
    s.account_id,
    toUInt64OrZero(s.product_id) AS product_id,
    any(s.nm_id) AS nm_id,
    any(s.ozon_product_id) AS ozon_product_id,
    coalesce(anyLast(p.name), '') AS product_name,
    sum(s.price_gross * s.qty) AS revenue_rub,
    sum(ifNull(s.payout, 0)) AS payout_rub,
    coalesce(anyLast(c.cost_price_rub), 0) AS cost_price_rub,
    sum(s.qty) * cost_price_rub AS total_cost_rub,
    payout_rub - total_cost_rub AS profit_rub,
    if(revenue_rub > 0, profit_rub / revenue_rub * 100, 0) AS margin_pct,
    toUInt32(sumIf(s.qty, s.is_return = 0)) AS quantity,
    toUInt32(-sumIf(s.qty, s.is_return = 1)) AS return_qty
FROM stg_sales AS s FINAL
LEFT JOIN dim_product_cost AS c FINAL
    ON s.marketplace = c.marketplace
    AND s.product_id = toString(c.product_id)
LEFT JOIN raw_competitor_products AS p FINAL
    ON s.marketplace = p.marketplace
    AND s.product_id = toString(p.product_id)
WHERE s.day >= toDate(now(), 'Europe/Moscow') - %(days)s
GROUP BY s.day, s.marketplace, s.account_id, s.product_id
