INSERT INTO mrt_competitor_daily
SELECT
    toDate(snapshot_ts) AS day,
    marketplace,
    product_id,
    anyLast(name) AS name,
    anyLast(brand) AS brand,
    anyLast(category_name) AS category_name,
    anyLast(supplier_name) AS supplier_name,
    anyLast(rating) AS rating,
    anyLast(review_count) AS review_count,
    argMax(price_rub, snapshot_ts) AS price_rub,
    argMax(price_old_rub, snapshot_ts) AS price_old_rub,
    argMax(sale_percent, snapshot_ts) AS sale_percent,
    argMax(in_stock, snapshot_ts) AS in_stock
FROM raw_competitor_prices AS pr
INNER JOIN raw_competitor_products AS p FINAL
    ON pr.marketplace = p.marketplace
    AND pr.product_id = p.product_id
WHERE snapshot_ts >= today() - %(days)s
GROUP BY day, marketplace, product_id
