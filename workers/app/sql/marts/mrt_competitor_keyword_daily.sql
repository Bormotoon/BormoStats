INSERT INTO mrt_competitor_keyword_daily
SELECT
    toDate(snapshot_ts) AS day,
    marketplace,
    query,
    position,
    argMax(product_id, snapshot_ts) AS product_id,
    argMax(price_rub, snapshot_ts) AS price_rub
FROM raw_competitor_search
WHERE snapshot_ts >= yesterday()
GROUP BY day, marketplace, query, position
ORDER BY day, marketplace, query, position
