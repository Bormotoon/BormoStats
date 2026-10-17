-- Monthly P&L per account from the finance block (costs are positive numbers):
--   revenue_rub       sales at the seller's price
--   returns_cost_rub  returned goods at the seller's price
--   commission_rub    commission and acquiring
--   logistics_rub     delivery, reverse logistics, acceptance
--   storage_rub       warehouse placement
--   other_costs_rub   penalties and other charges (net of compensations; WB ads are
--                     deducted here)
--   net_accrued_rub   what the marketplace accrued to the balance: revenue minus all above
--   cogs_rub          cost price x units kept by buyers (v_offer_cost by supplier article,
--                     else dim_product_cost; 0 without costs)
--   gross_profit_rub  net_accrued_rub - cogs_rub
--   ad_cost_rub       Ozon Performance spend (mrt_ads_daily; paid outside the balance)
--   operating/ebitda/net profit: gross profit - ads (indirect expenses are separate rows,
--                     see mrt_pnl_monthly_expenses.sql; no depreciation or tax data)
--   margin_pct        gross_profit_rub / (revenue_rub - returns_cost_rub)
INSERT INTO mrt_pnl_monthly
(
  month, organization_id, marketplace, account_id,
  revenue_rub, commission_rub, logistics_rub, returns_cost_rub, storage_rub, other_costs_rub,
  net_accrued_rub, cogs_rub, gross_profit_rub, ad_cost_rub, additional_expenses_rub,
  operating_profit_rub, ebitda_rub, net_profit_rub, margin_pct, updated_at
)
WITH
  toStartOfMonth(toDate(now(), 'Europe/Moscow') - %(days)s) AS from_month,
  finance AS
  (
    SELECT
      toStartOfMonth(day) AS month,
      marketplace,
      account_id,
      sum(sales) AS sales,
      sum(returns) AS returns,
      sum(commission + acquiring) AS commission,
      sum(logistics + reverse_logistics + acceptance) AS logistics,
      sum(storage) AS storage,
      sum(penalties + other) AS other,
      sum(net_accrued) AS net_accrued
    FROM mrt_finance_daily FINAL
    WHERE day >= from_month
    GROUP BY month, marketplace, account_id
  ),
  cogs AS
  (
    SELECT
      toStartOfMonth(s.day) AS month,
      s.marketplace AS marketplace,
      s.account_id AS account_id,
      sum(s.qty * if(ifNull(oc.cost_price_rub, 0) > 0, oc.cost_price_rub,
        ifNull(c.cost_price_rub, 0))) AS cogs
    FROM stg_sales AS s FINAL
    LEFT JOIN dim_product_cost AS c FINAL
      ON s.marketplace = c.marketplace
      AND s.product_id = toString(c.product_id)
    LEFT JOIN v_offer_cost AS oc
      ON s.marketplace = oc.marketplace
      AND s.account_id = oc.account_id
      AND s.product_id = oc.product_id
    WHERE s.day >= from_month
    GROUP BY month, s.marketplace, s.account_id
  ),
  ads AS
  (
    SELECT toStartOfMonth(day) AS month, marketplace, account_id, sum(cost) AS cost
    FROM mrt_ads_daily FINAL
    WHERE day >= from_month
    GROUP BY month, marketplace, account_id
  )
SELECT
  f.month,
  a.organization_id,
  f.marketplace,
  f.account_id,
  f.sales AS revenue_rub,
  -f.commission AS commission_rub,
  -f.logistics AS logistics_rub,
  -f.returns AS returns_cost_rub,
  -f.storage AS storage_rub,
  -f.other AS other_costs_rub,
  f.net_accrued AS net_accrued_rub,
  ifNull(cg.cogs, 0) AS cogs_rub,
  net_accrued_rub - cogs_rub AS gross_profit_rub,
  ifNull(ad.cost, 0) AS ad_cost_rub,
  0 AS additional_expenses_rub,
  gross_profit_rub - ad_cost_rub AS operating_profit_rub,
  operating_profit_rub AS ebitda_rub,
  operating_profit_rub AS net_profit_rub,
  if(revenue_rub - returns_cost_rub > 0,
     gross_profit_rub / (revenue_rub - returns_cost_rub) * 100, 0) AS margin_pct,
  now() AS updated_at
FROM finance AS f
INNER JOIN (SELECT marketplace, account_id, organization_id FROM dim_account FINAL) AS a
  ON f.marketplace = a.marketplace AND f.account_id = a.account_id
LEFT JOIN cogs AS cg
  ON f.month = cg.month AND f.marketplace = cg.marketplace AND f.account_id = cg.account_id
LEFT JOIN ads AS ad
  ON f.month = ad.month AND f.marketplace = ad.marketplace AND f.account_id = ad.account_id
SETTINGS join_use_nulls = 1
