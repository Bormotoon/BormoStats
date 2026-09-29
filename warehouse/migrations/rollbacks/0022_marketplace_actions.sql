DROP TABLE IF EXISTS sys_marketplace_actions;
ALTER TABLE dim_price_rule DROP COLUMN IF EXISTS dry_run;
ALTER TABLE dim_ad_rule DROP COLUMN IF EXISTS placement;
ALTER TABLE dim_ad_rule DROP COLUMN IF EXISTS product_id;
ALTER TABLE dim_ad_rule DROP COLUMN IF EXISTS dry_run;
