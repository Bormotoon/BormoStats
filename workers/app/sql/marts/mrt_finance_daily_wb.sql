-- WB finance per Moscow day: realization report lines summed per operation day (their
-- net_accrued is WB's "Итого к оплате"), and the balance widget's last snapshot of the
-- day. Today has a balance before WB forms the day's report, hence the full join. WB
-- publishes no payout history, so payouts and the opening balance stay NULL.
INSERT INTO mrt_finance_daily
(
  day, marketplace, account_id,
  sales, returns, commission, acquiring, logistics, reverse_logistics, storage, acceptance,
  penalties, other, net_accrued,
  payouts, opening_balance, closing_balance, for_withdraw, details, updated_at
)
WITH toDate(now(), 'Europe/Moscow') AS today_msk
SELECT
  day, 'wb' AS marketplace, account_id,
  ifNull(r.sales, 0), ifNull(r.returns, 0), ifNull(r.commission, 0), ifNull(r.acquiring, 0),
  ifNull(r.logistics, 0), ifNull(r.reverse_logistics, 0), ifNull(r.storage, 0),
  ifNull(r.acceptance, 0), ifNull(r.penalties, 0), ifNull(r.other, 0),
  ifNull(r.net_accrued, 0),
  NULL AS payouts, NULL AS opening_balance, b.balance AS closing_balance, b.for_withdraw,
  r.details, now() AS updated_at
FROM
(
  SELECT
    w.day AS day,
    w.account_id AS account_id,
    sum(w.sales) AS sales,
    sum(w.returns) AS returns,
    sum(w.commission) AS commission,
    sum(w.acquiring) AS acquiring,
    sum(w.logistics) AS logistics,
    sum(w.reverse_logistics) AS reverse_logistics,
    sum(w.storage) AS storage,
    sum(w.acceptance) AS acceptance,
    sum(w.penalties) AS penalties,
    sum(w.other) AS other,
    sum(w.net_accrued) AS net_accrued,
    -- net accrual per operation type, e.g. "Продажа", "Логистика", "Хранение"
    sumMap(map(toString(w.oper_name), w.net_accrued)) AS details
  FROM raw_wb_sales_report AS w FINAL
  WHERE w.day >= today_msk - %(days)s
  GROUP BY w.day, w.account_id
) AS r
FULL OUTER JOIN
(
  SELECT
    toDate(snapshot_ts, 'Europe/Moscow') AS day,
    account_id,
    argMax(balance, snapshot_ts) AS balance,
    argMax(for_withdraw, snapshot_ts) AS for_withdraw
  FROM raw_marketplace_balance FINAL
  WHERE marketplace = 'wb' AND snapshot_ts >= now() - toIntervalDay(%(days)s + 2)
  GROUP BY day, account_id
  HAVING day >= today_msk - %(days)s
) AS b USING (day, account_id)
SETTINGS join_use_nulls = 1
