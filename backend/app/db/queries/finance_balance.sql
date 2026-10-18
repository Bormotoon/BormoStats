-- The latest balance snapshot per account: WB's balance widget (current, for_withdraw),
-- Ozon's closing balance of today. Collected hourly. last_payout_day is the last Moscow day
-- money was paid out (Ozon only: WB does not report payouts), so the balance is what has
-- accrued since then.
SELECT
  b.marketplace AS marketplace,
  b.account_id AS account_id,
  argMax(b.balance, b.snapshot_ts) AS balance,
  argMax(b.for_withdraw, b.snapshot_ts) AS for_withdraw,
  max(b.snapshot_ts) AS as_of,
  nullIf(any(p.last_payout_day), toDate(0)) AS last_payout_day
FROM raw_marketplace_balance AS b FINAL
LEFT JOIN (
  SELECT marketplace, account_id, max(day) AS last_payout_day
  FROM mrt_finance_daily FINAL
  WHERE ifNull(payouts, 0) != 0
  GROUP BY marketplace, account_id
) AS p ON p.marketplace = b.marketplace AND p.account_id = b.account_id
WHERE (%(marketplace)s = '' OR b.marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR b.account_id = %(account_id)s)
  AND (b.marketplace, b.account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
GROUP BY b.marketplace, b.account_id
ORDER BY b.marketplace, b.account_id
LIMIT %(limit)s
OFFSET %(offset)s
