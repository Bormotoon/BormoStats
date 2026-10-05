-- The latest balance snapshot per account: WB's balance widget (current, for_withdraw),
-- Ozon's closing balance of today. Collected hourly.
SELECT
  marketplace,
  account_id,
  argMax(balance, snapshot_ts) AS balance,
  argMax(for_withdraw, snapshot_ts) AS for_withdraw,
  max(snapshot_ts) AS as_of
FROM raw_marketplace_balance FINAL
WHERE (%(marketplace)s = '' OR marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR account_id = %(account_id)s)
  AND (marketplace, account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
GROUP BY marketplace, account_id
ORDER BY marketplace, account_id
LIMIT %(limit)s
OFFSET %(offset)s
