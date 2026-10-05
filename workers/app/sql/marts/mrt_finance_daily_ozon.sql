-- Ozon finance per Moscow day, as the balance method reports it (common/finance.py):
-- categories adding up to net_accrued, payouts, opening and closing balance.
INSERT INTO mrt_finance_daily
(
  day, marketplace, account_id,
  sales, returns, commission, acquiring, logistics, reverse_logistics, storage, acceptance,
  penalties, other, net_accrued,
  payouts, opening_balance, closing_balance, for_withdraw, details, updated_at
)
SELECT
  day, 'ozon' AS marketplace, account_id,
  sales, returns, commission, acquiring, logistics, reverse_logistics, storage, acceptance,
  penalties, other, net_accrued,
  payouts, opening_balance, closing_balance, NULL AS for_withdraw, services AS details,
  now() AS updated_at
FROM raw_ozon_finance_balance FINAL
WHERE day >= toDate(now(), 'Europe/Moscow') - %(days)s
