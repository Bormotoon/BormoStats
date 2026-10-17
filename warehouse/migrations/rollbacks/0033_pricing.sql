DROP VIEW IF EXISTS v_offer_cost;
DROP TABLE IF EXISTS mrt_price_current;
ALTER TABLE dim_price_rule DROP COLUMN IF EXISTS max_step_pct;
ALTER TABLE dim_price_rule DROP COLUMN IF EXISTS target_price;
ALTER TABLE dim_price_rule DROP COLUMN IF EXISTS mode;
DROP TABLE IF EXISTS dim_offer_cost;
