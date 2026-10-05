ALTER TABLE mrt_pnl_monthly DROP COLUMN IF EXISTS cogs_rub;
ALTER TABLE mrt_pnl_monthly DROP COLUMN IF EXISTS net_accrued_rub;
ALTER TABLE mrt_pnl_monthly DROP COLUMN IF EXISTS other_costs_rub;
ALTER TABLE mrt_pnl_monthly DROP COLUMN IF EXISTS storage_rub;
DROP TABLE IF EXISTS mrt_finance_daily;
DROP TABLE IF EXISTS raw_marketplace_balance;
DROP TABLE IF EXISTS raw_wb_sales_report;
DROP TABLE IF EXISTS raw_ozon_finance_balance;
