SELECT
  day,
  type,
  round(sum(amount), 2) AS amount
FROM stg_finance_ops
WHERE day BETWEEN {{from}} AND {{to}}
GROUP BY day, type
ORDER BY day, type;
