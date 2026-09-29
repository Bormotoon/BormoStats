-- Ozon finance: /v3/finance/transaction/list was switched off on 2026-09-08; rows now come
-- from /v1/finance/accrual/by-day. Existing rows keep the legacy source so the staging
-- transform can prefer accruals for days that were collected with the new method.
ALTER TABLE raw_ozon_finance_ops ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'transaction_list_v3';
