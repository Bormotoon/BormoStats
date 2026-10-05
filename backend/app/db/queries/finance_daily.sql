-- Finance per Moscow day and account (common/finance.py): categories add up to
-- net_accrued; payouts and the opening balance are known for Ozon only.
SELECT
  day,
  marketplace,
  account_id,
  sales,
  returns,
  commission,
  acquiring,
  logistics,
  reverse_logistics,
  storage,
  acceptance,
  penalties,
  other,
  net_accrued,
  payouts,
  opening_balance,
  closing_balance,
  for_withdraw,
  details
FROM mrt_finance_daily FINAL
WHERE day BETWEEN %(date_from)s AND %(date_to)s
  AND (%(marketplace)s = '' OR marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR account_id = %(account_id)s)
  AND (marketplace, account_id) IN (
    SELECT marketplace, account_id FROM dim_account FINAL WHERE organization_id = %(organization_id)s
  )
ORDER BY day, marketplace, account_id
LIMIT %(limit)s
OFFSET %(offset)s
