INSERT INTO mrt_competitor_category_daily
SELECT
    toDate(now()) AS day,
    p.marketplace,
    p.category_id,
    anyLast(p.category_name) AS category_name,
    count(DISTINCT p.product_id) AS tracked_products,
    count(DISTINCT p.supplier_id) AS supplier_count,
    count(DISTINCT p.brand) AS brand_count,
    avg(p.rating) AS avg_rating,
    min(pr.price_rub) AS min_price,
    max(pr.price_rub) AS max_price,
    avg(pr.price_rub) AS avg_price,
    sum(pr.in_stock) AS total_stock
FROM raw_competitor_products FINAL AS p
INNER JOIN (
    SELECT
        marketplace,
        product_id,
        argMax(price_rub, snapshot_ts) AS price_rub,
        argMax(in_stock, snapshot_ts) AS in_stock
    FROM raw_competitor_prices
    WHERE snapshot_ts >= yesterday()
    GROUP BY marketplace, product_id
) AS pr
    ON p.marketplace = pr.marketplace
    AND p.product_id = pr.product_id
WHERE p.category_id > 0
GROUP BY day, p.marketplace, p.category_id
