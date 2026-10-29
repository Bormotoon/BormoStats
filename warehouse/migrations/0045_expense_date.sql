-- Preserve existing monthly expenses; new entries can belong to an actual day.
ALTER TABLE dim_additional_expense ADD COLUMN IF NOT EXISTS expense_date Nullable(Date) AFTER month;
