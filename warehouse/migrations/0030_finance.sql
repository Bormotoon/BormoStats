-- Finance block: balances, payouts and every charge, per Moscow day (common/finance.py).
-- Category columns are signed from the seller's point of view and add up to net_accrued.

-- Ozon /v1/finance/balance, called for one day at a time
CREATE TABLE IF NOT EXISTS raw_ozon_finance_balance
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  sales Float64,
  returns Float64,
  commission Float64,
  acquiring Float64,
  logistics Float64,
  reverse_logistics Float64,
  storage Float64,
  acceptance Float64,
  penalties Float64,
  other Float64,
  net_accrued Float64,
  payouts Float64,
  opening_balance Float64,
  closing_balance Float64,
  services Map(String, Float64),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day);

-- WB realization report lines (/api/finance/v1/sales-reports/detailed, daily reports)
CREATE TABLE IF NOT EXISTS raw_wb_sales_report
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  rrd_id UInt64,
  report_id UInt64,
  report_type UInt8,
  day Date,
  nm_id UInt64,
  doc_type LowCardinality(String),
  oper_name LowCardinality(String),
  quantity Int32,
  sales Float64,
  returns Float64,
  commission Float64,
  acquiring Float64,
  logistics Float64,
  reverse_logistics Float64,
  storage Float64,
  acceptance Float64,
  penalties Float64,
  other Float64,
  net_accrued Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, rrd_id);

-- balance snapshots (WB balance widget, Ozon closing balance of today); snapshot_ts is a
-- true instant
CREATE TABLE IF NOT EXISTS raw_marketplace_balance
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  snapshot_ts DateTime,
  balance Float64,
  for_withdraw Nullable(Float64),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (marketplace, account_id, snapshot_ts);

CREATE TABLE IF NOT EXISTS mrt_finance_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  sales Float64,
  returns Float64,
  commission Float64,
  acquiring Float64,
  logistics Float64,
  reverse_logistics Float64,
  storage Float64,
  acceptance Float64,
  penalties Float64,
  other Float64,
  net_accrued Float64,
  payouts Nullable(Float64),
  opening_balance Nullable(Float64),
  closing_balance Nullable(Float64),
  for_withdraw Nullable(Float64),
  details Map(String, Float64),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day);

-- P&L: the marketplace charges without a column so far, cost of goods, and the accrual
ALTER TABLE mrt_pnl_monthly ADD COLUMN IF NOT EXISTS storage_rub Float64 DEFAULT 0;
ALTER TABLE mrt_pnl_monthly ADD COLUMN IF NOT EXISTS other_costs_rub Float64 DEFAULT 0;
ALTER TABLE mrt_pnl_monthly ADD COLUMN IF NOT EXISTS net_accrued_rub Float64 DEFAULT 0;
ALTER TABLE mrt_pnl_monthly ADD COLUMN IF NOT EXISTS cogs_rub Float64 DEFAULT 0;
