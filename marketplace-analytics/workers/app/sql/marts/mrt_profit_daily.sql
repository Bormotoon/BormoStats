INSERT INTO mrt_profit_daily
SELECT
    s.day,
    s.marketplace,
    s.account_id,
    s.product_id,
    s.nm_id,
    s.ozon_product_id,
    coalesce(anyLast(p.name), '') AS product_name,
    sum(if(s.is_return = 0, s.price_gross, 0)) AS revenue_rub,
    sum(if(s.is_return = 0, s.payout, 0)) AS payout_rub,
    coalesce(anyLast(c.cost_price_rub), 0) AS cost_price_rub,
    sum(if(s.is_return = 0, s.qty, 0)) * coalesce(anyLast(c.cost_price_rub), 0) AS total_cost_rub,
    sum(if(s.is_return = 0, s.payout, 0)) - sum(if(s.is_return = 0, s.qty, 0)) * coalesce(anyLast(c.cost_price_rub), 0) AS profit_rub,
    if(
        sum(if(s.is_return = 0, s.payout, 0)) > 0,
        (sum(if(s.is_return = 0, s.payout, 0)) - sum(if(s.is_return = 0, s.qty, 0)) * coalesce(anyLast(c.cost_price_rub), 0)) / sum(if(s.is_return = 0, s.payout, 0)) * 100,
        0
    ) AS margin_pct,
    sum(if(s.is_return = 0, s.qty, 0)) AS quantity,
    sum(if(s.is_return = 1, s.qty, 0)) AS return_qty
FROM stg_sales FINAL AS s
LEFT JOIN dim_product_cost FINAL AS c
    ON s.marketplace = c.marketplace
    AND s.product_id = c.product_id
LEFT JOIN raw_competitor_products FINAL AS p
    ON s.marketplace = p.marketplace
    AND s.product_id = p.product_id
WHERE s.day >= today() - %(days)s
GROUP BY s.day, s.marketplace, s.account_id, s.product_id, s.nm_id, s.ozon_product_id
