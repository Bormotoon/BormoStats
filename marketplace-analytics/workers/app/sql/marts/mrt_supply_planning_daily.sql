INSERT INTO mrt_supply_planning_daily
SELECT
    today() AS day,
    s.marketplace,
    s.account_id,
    s.product_id,
    coalesce(anyLast(p.name), '') AS product_name,
    coalesce(avg(if(s.day >= today() - 7, s.qty, NULL)), 0) AS avg_sales_7d,
    coalesce(avg(if(s.day >= today() - 14, s.qty, NULL)), 0) AS avg_sales_14d,
    coalesce(avg(if(s.day >= today() - 30, s.qty, NULL)), 0) AS avg_sales_30d,
    coalesce(st.latest_stock, 0) AS latest_stock,
    multiIf(
        coalesce(avg(if(s.day >= today() - 14, s.qty, NULL)), 0) > 0,
        coalesce(st.latest_stock, 0) / avg(if(s.day >= today() - 14, s.qty, NULL)),
        999
    ) AS days_until_stockout,
    multiIf(
        coalesce(avg(if(s.day >= today() - 14, s.qty, NULL)), 0) > 0
        AND coalesce(st.latest_stock, 0) < avg(if(s.day >= today() - 14, s.qty, NULL)) * 21,
        toUInt32(ceil(avg(if(s.day >= today() - 14, s.qty, NULL)) * 30 - coalesce(st.latest_stock, 0))),
        0
    ) AS reorder_qty,
    multiIf(
        coalesce(st.latest_stock, 0) <= 0, 1,
        coalesce(avg(if(s.day >= today() - 14, s.qty, NULL)), 0) > 0
        AND coalesce(st.latest_stock, 0) / avg(if(s.day >= today() - 14, s.qty, NULL)) < 14, 1,
        0
    ) AS is_critical
FROM stg_sales FINAL AS s
LEFT JOIN (
    SELECT
        marketplace,
        account_id,
        product_id,
        argMax(amount, snapshot_ts) AS latest_stock
    FROM stg_stocks FINAL
    WHERE snapshot_ts >= today() - 1
    GROUP BY marketplace, account_id, product_id
) AS st
    ON s.marketplace = st.marketplace
    AND s.account_id = st.account_id
    AND s.product_id = st.product_id
LEFT JOIN raw_competitor_products FINAL AS p
    ON s.marketplace = p.marketplace
    AND s.product_id = p.product_id
WHERE s.day >= today() - 30
    AND s.is_return = 0
GROUP BY s.marketplace, s.account_id, s.product_id
