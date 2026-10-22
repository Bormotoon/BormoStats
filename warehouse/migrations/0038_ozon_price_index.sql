-- Ozon's price index colour of a card (price_indexes.color_index of /v5/product/info/prices:
-- SUPER, GREEN, YELLOW, RED or WITHOUT_INDEX; '' on WB). RED means buyers pay noticeably more on
-- Ozon than for the same item elsewhere, and Ozon cuts its "баллы за скидки" then; the
-- repricer lowers such a card (workers/app/tasks/repricer.py).
ALTER TABLE mrt_price_current ADD COLUMN IF NOT EXISTS price_index_color LowCardinality(String) DEFAULT '' AFTER auto_actions_enabled;
