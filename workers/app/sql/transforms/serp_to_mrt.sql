INSERT INTO mrt_keyword_positions_daily (day, marketplace, account_id, keyword, product_id, avg_position, min_position, max_position, checks_count, updated_at)
SELECT
  toDate(search_ts) AS day,
  marketplace,
  account_id,
  keyword,
  product_id,
  avg(position) AS avg_position,
  min(position) AS min_position,
  max(position) AS max_position,
  count() AS checks_count,
  now()
FROM raw_serp_positions
WHERE search_ts >= yesterday()
GROUP BY day, marketplace, account_id, keyword, product_id
