INSERT INTO stg_finance_ops
(operation_ts, marketplace, account_id, operation_id, type, amount, currency, meta_json, ingested_at)
SELECT toDateTime(event_date), 'ym', account_id, transaction_id,
  concat(transaction_type, ':', service_type), amount, 'RUB', payload, ingested_at
FROM raw_ym_finance FINAL
WHERE event_date >= toDate(now(), 'Europe/Moscow') - %(days)s;
