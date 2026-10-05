-- Today's ABC/XYZ classes per product.
-- ABC: share of sales revenue over the last 60 full Moscow days (A up to 80 % cumulative,
--      B up to 95 %, C the rest).
-- XYZ: coefficient of variation of the weekly quantity over the last 8 full weeks
--      (56 days before today), weeks without sales counted as zero (X < 10 %, Y < 25 %,
--      Z otherwise). Daily quantities are too sparse for these thresholds: a product
--      selling a few units a day would always be Z.
--      daily_mean_qty = units per day over the 56 days; daily_stddev_qty = standard
--      deviation of the weekly quantity divided by 7.
INSERT INTO mrt_abc_xyz_analysis (day, marketplace, account_id, product_id, revenue_60d, share_pct, cumulative_share_pct, abc_class, daily_mean_qty, daily_stddev_qty, cv_pct, xyz_class, updated_at)
WITH
toDate(now(), 'Europe/Moscow') AS today_msk,
revenue_60d AS (
  SELECT
    marketplace,
    account_id,
    product_id,
    sum(revenue) AS revenue_60d
  FROM mrt_sales_daily FINAL
  WHERE day >= today_msk - 60 AND day < today_msk
  GROUP BY marketplace, account_id, product_id
  HAVING revenue_60d > 0
),
total_revenue AS (
  SELECT marketplace, account_id, sum(revenue_60d) AS total
  FROM revenue_60d
  GROUP BY marketplace, account_id
),
with_share AS (
  SELECT
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
    marketplace, account_id, product_id, revenue_60d, share_pct,
    sum(share_pct) OVER (
      PARTITION BY marketplace, account_id
      ORDER BY share_pct DESC, product_id
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_share_pct
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
weekly AS (
  SELECT
    marketplace,
    account_id,
    product_id,
    intDiv(toUInt32(today_msk - 1 - day), 7) AS week_no,
    sum(qty) AS week_qty
  FROM mrt_sales_daily FINAL
  WHERE day >= today_msk - 56 AND day < today_msk
  GROUP BY marketplace, account_id, product_id, week_no
),
weekly_stats AS (
  -- 8 weeks, the ones without a row sold nothing: sums over the rows are sums over all 8
  SELECT
    marketplace,
    account_id,
    product_id,
    sum(week_qty) / 8 AS mean_week,
    sqrt(greatest(sum(week_qty * week_qty) - 8 * pow(sum(week_qty) / 8, 2), 0) / 7) AS stddev_week
  FROM weekly
  GROUP BY marketplace, account_id, product_id
),
with_xyz AS (
  SELECT
    marketplace,
    account_id,
    product_id,
    1 AS has_weeks,
    mean_week / 7 AS daily_mean_qty,
    stddev_week / 7 AS daily_stddev_qty,
    if(mean_week > 0, stddev_week / mean_week * 100, 999) AS cv_pct,
    CASE
      WHEN mean_week <= 0 THEN 'Z'
      WHEN stddev_week / mean_week * 100 < 10 THEN 'X'
      WHEN stddev_week / mean_week * 100 < 25 THEN 'Y'
      ELSE 'Z'
    END AS xyz_class
  FROM weekly_stats
)
SELECT
  today_msk AS day,
  a.marketplace,
  a.account_id,
  a.product_id,
  a.revenue_60d,
  a.share_pct,
  a.cumulative_share_pct,
  a.abc_class,
  s.daily_mean_qty,
  s.daily_stddev_qty,
  -- sold only in the days before the 8 weeks: no weekly rows, no stable demand
  if(s.has_weeks = 1, s.cv_pct, 999) AS cv_pct,
  if(s.has_weeks = 1, s.xyz_class, 'Z') AS xyz_class,
  now()
FROM with_abc a
LEFT JOIN with_xyz s USING (marketplace, account_id, product_id)
