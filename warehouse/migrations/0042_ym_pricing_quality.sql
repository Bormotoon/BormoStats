ALTER TABLE mrt_price_current ADD COLUMN IF NOT EXISTS ym_costs_ready Nullable(UInt8) DEFAULT NULL;
ALTER TABLE mrt_price_current ADD COLUMN IF NOT EXISTS ym_fee_source String DEFAULT '';
