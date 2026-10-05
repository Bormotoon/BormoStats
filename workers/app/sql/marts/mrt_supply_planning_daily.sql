-- Today's supply plan per product that sold in the last 30 full Moscow days.
--   avg_sales_Nd         units sold per day over the last N full days (days without
--                        sales count as zero; today is excluded as it is incomplete)
--   latest_stock         available units over all warehouses in the latest snapshot
--   days_until_stockout  latest_stock / avg_sales_14d (999 without sales)
--   reorder_qty          30 days of cover when less than 21 days are left
--   is_critical          out of stock, or less than 14 days of cover
INSERT INTO mrt_supply_planning_daily
WITH
  toDate(now(), 'Europe/Moscow') AS today_msk,
  sales AS
  (
    SELECT
      marketplace,
      account_id,
      product_id,
      sumIf(qty, day >= today_msk - 7) / 7 AS avg_sales_7d,
      sumIf(qty, day >= today_msk - 14) / 14 AS avg_sales_14d,
      sum(qty) / 30 AS avg_sales_30d
    FROM stg_sales FINAL
    WHERE is_return = 0
      AND day >= today_msk - 30
      AND day < today_msk
    GROUP BY marketplace, account_id, product_id
  ),
  latest_snapshot AS
  (
    SELECT marketplace, account_id, max(snapshot_ts) AS snapshot_ts
    FROM stg_stocks FINAL
    WHERE day >= today_msk - 1
    GROUP BY marketplace, account_id
  ),
  stock AS
  (
    SELECT s.marketplace, s.account_id, s.product_id, sum(s.amount) AS latest_stock
    FROM stg_stocks AS s FINAL
    INNER JOIN latest_snapshot AS l
      ON s.marketplace = l.marketplace
      AND s.account_id = l.account_id
      AND s.snapshot_ts = l.snapshot_ts
    WHERE s.day >= today_msk - 1
    GROUP BY s.marketplace, s.account_id, s.product_id
  )
SELECT
  today_msk AS day,
  sa.marketplace,
  sa.account_id,
  toUInt64OrZero(sa.product_id) AS product_id,
  coalesce(anyLast(p.name), '') AS product_name,
  any(sa.avg_sales_7d) AS avg_sales_7d,
  any(sa.avg_sales_14d) AS avg_sales_14d,
  any(sa.avg_sales_30d) AS avg_sales_30d,
  toInt32(any(st.latest_stock)) AS latest_stock,
  if(avg_sales_14d > 0, latest_stock / avg_sales_14d, 999) AS days_until_stockout,
  if(
    avg_sales_14d > 0 AND latest_stock < avg_sales_14d * 21,
    toUInt32(greatest(ceil(avg_sales_14d * 30 - latest_stock), 0)),
    0
  ) AS reorder_qty,
  multiIf(
    latest_stock <= 0, 1,
    avg_sales_14d > 0 AND latest_stock / avg_sales_14d < 14, 1,
    0
  ) AS is_critical
FROM sales AS sa
LEFT JOIN stock AS st
  ON sa.marketplace = st.marketplace
  AND sa.account_id = st.account_id
  AND sa.product_id = st.product_id
LEFT JOIN (
  SELECT marketplace, account_id, product_id, anyLast(title) AS name
  FROM dim_product FINAL
  WHERE title IS NOT NULL
  GROUP BY marketplace, account_id, product_id
) AS p
  ON sa.marketplace = p.marketplace
  AND sa.account_id = p.account_id
  AND sa.product_id = p.product_id
GROUP BY sa.marketplace, sa.account_id, sa.product_id
