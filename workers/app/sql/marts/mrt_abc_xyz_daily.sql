INSERT INTO mrt_abc_xyz_analysis (day, marketplace, account_id, product_id, revenue_60d, share_pct, cumulative_share_pct, abc_class, daily_mean_qty, daily_stddev_qty, cv_pct, xyz_class, updated_at)
WITH
revenue_60d AS (
  SELECT
    today() AS day,
    marketplace,
    account_id,
    product_id,
    sum(revenue) AS revenue_60d
  FROM mrt_sales_daily
  WHERE day >= today() - 60
  GROUP BY marketplace, account_id, product_id
),
total_revenue AS (
  SELECT marketplace, account_id, sum(revenue_60d) AS total
  FROM revenue_60d
  GROUP BY marketplace, account_id
),
with_share AS (
  SELECT
    r.day,
    r.marketplace,
    r.account_id,
    r.product_id,
    r.revenue_60d,
    if(t.total > 0, r.revenue_60d / t.total, 0) AS share_pct
  FROM revenue_60d r
  JOIN total_revenue t USING (marketplace, account_id)
),
with_cumulative AS (
  SELECT
    day, marketplace, account_id, product_id, revenue_60d, share_pct,
    sum(share_pct) OVER (PARTITION BY marketplace, account_id ORDER BY share_pct DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_share_pct
  FROM with_share
),
with_abc AS (
  SELECT *,
    CASE
      WHEN cumulative_share_pct <= 0.80 THEN 'A'
      WHEN cumulative_share_pct <= 0.95 THEN 'B'
      ELSE 'C'
    END AS abc_class
  FROM with_cumulative
),
daily_stats AS (
  SELECT
    marketplace,
    account_id,
    product_id,
    avg(qty) AS daily_mean_qty,
    stddevSamp(qty) AS daily_stddev_qty
  FROM mrt_sales_daily
  WHERE day >= today() - 60
  GROUP BY marketplace, account_id, product_id
),
with_xyz AS (
  SELECT *,
    IF(daily_mean_qty > 0, (daily_stddev_qty / daily_mean_qty) * 100, 999) AS cv_pct,
    CASE
      WHEN daily_mean_qty <= 0 OR (daily_stddev_qty / daily_mean_qty) * 100 IS NULL THEN 'Z'
      WHEN (daily_stddev_qty / daily_mean_qty) * 100 < 10 THEN 'X'
      WHEN (daily_stddev_qty / daily_mean_qty) * 100 < 25 THEN 'Y'
      ELSE 'Z'
    END AS xyz_class
  FROM daily_stats
)
SELECT
  a.day,
  a.marketplace,
  a.account_id,
  a.product_id,
  a.revenue_60d,
  a.share_pct,
  a.cumulative_share_pct,
  a.abc_class,
  s.daily_mean_qty,
  s.daily_stddev_qty,
  s.cv_pct,
  s.xyz_class,
  now()
FROM with_abc a
LEFT JOIN with_xyz s USING (marketplace, account_id, product_id)
