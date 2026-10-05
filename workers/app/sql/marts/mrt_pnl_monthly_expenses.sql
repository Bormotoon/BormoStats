-- Indirect expenses (dim_additional_expense) belong to the organization, not to a
-- marketplace account: one row per organization and month with marketplace = ''.
INSERT INTO mrt_pnl_monthly
(
  month, organization_id, marketplace, account_id,
  revenue_rub, commission_rub, logistics_rub, returns_cost_rub, storage_rub, other_costs_rub,
  net_accrued_rub, cogs_rub, gross_profit_rub, ad_cost_rub, additional_expenses_rub,
  operating_profit_rub, ebitda_rub, net_profit_rub, margin_pct, updated_at
)
SELECT
  toStartOfMonth(month) AS month,
  organization_id,
  '' AS marketplace,
  '' AS account_id,
  0, 0, 0, 0, 0, 0,
  0, 0, 0, 0,
  sum(amount_rub) AS additional_expenses_rub,
  -additional_expenses_rub AS operating_profit_rub,
  operating_profit_rub AS ebitda_rub,
  operating_profit_rub AS net_profit_rub,
  0 AS margin_pct,
  now() AS updated_at
FROM dim_additional_expense FINAL
WHERE month >= toStartOfMonth(toDate(now(), 'Europe/Moscow') - %(days)s)
GROUP BY month, organization_id
