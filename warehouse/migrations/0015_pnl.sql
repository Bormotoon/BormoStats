-- P&L: Indirect expenses and monthly P&L view

CREATE TABLE IF NOT EXISTS dim_additional_expense
(
  expense_id String,
  organization_id LowCardinality(String),
  category LowCardinality(String),
  amount_rub Float64,
  month Date,
  description String,
  created_at DateTime DEFAULT now(),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, month, expense_id);

CREATE TABLE IF NOT EXISTS mrt_pnl_monthly
(
  month Date,
  organization_id LowCardinality(String),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  revenue_rub Float64,
  commission_rub Float64,
  logistics_rub Float64,
  returns_cost_rub Float64,
  gross_profit_rub Float64,
  ad_cost_rub Float64,
  additional_expenses_rub Float64,
  operating_profit_rub Float64,
  ebitda_rub Float64,
  net_profit_rub Float64,
  margin_pct Float32,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(month)
ORDER BY (month, organization_id, marketplace, account_id);
