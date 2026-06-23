INSERT INTO mrt_competitor_keyword_daily
SELECT
    toDate(snapshot_ts) AS day,
    marketplace,
    query,
    argMin(position, position) AS position,
    argMin(product_id, position) AS product_id,
    argMin(price_rub, position) AS price_rub
FROM raw_competitor_search
WHERE snapshot_ts >= yesterday()
GROUP BY day, marketplace, query, position
ORDER BY day, marketplace, query, position
