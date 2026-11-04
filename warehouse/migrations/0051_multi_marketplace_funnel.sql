ALTER TABLE raw_ozon_funnel_import
    ADD COLUMN IF NOT EXISTS marketplace LowCardinality(String) DEFAULT 'ozon' AFTER account_id;

