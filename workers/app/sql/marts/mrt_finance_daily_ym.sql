INSERT INTO mrt_finance_daily
(day, marketplace, account_id, sales, returns, commission, acquiring, logistics, reverse_logistics,
 storage, acceptance, penalties, other, net_accrued, payouts, opening_balance, closing_balance,
 for_withdraw, details, updated_at)
SELECT event_date, 'ym', account_id,
  sumIf(amount, category = 'sales'), sumIf(amount, category = 'returns'),
  sumIf(amount, category = 'commission'), sumIf(amount, category = 'acquiring'),
  sumIf(amount, category = 'logistics'), sumIf(amount, category = 'reverse_logistics'),
  sumIf(amount, category = 'storage'), sumIf(amount, category = 'acceptance'),
  sumIf(amount, category = 'penalties'), sumIf(amount, category = 'other'),
  sumIf(amount, category != 'payouts'),
  sumIf(if(amount != 0, amount, -abs(payout)), category = 'payouts'),
  NULL, NULL, NULL,
  sumMapIf(
    map(if(service_type != '', service_type, transaction_type), amount),
    category != 'payouts'
  ),
  now()
FROM
(
  SELECT event_date, account_id, transaction_type, service_type, amount, payout,
    multiIf(
      payout != 0 OR match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'payout|выплат|перечисление продавцу'), 'payouts',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'reverse|return.*(delivery|logistic|processing)|возвратная логист|невыкуп'), 'reverse_logistics',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'commission|(^| )fee( |$)|размещен|комисс'), 'commission',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'acquir|agency|payment_transfer|прием.*платеж|приём.*платеж'), 'acquiring',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'delivery|logistic|sorting|достав|складская обработка'), 'logistics',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'storage|хранен'), 'storage',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'accept|приемк|приёмк'), 'acceptance',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'penalt|штраф'), 'penalties',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'буст.*продаж|продаж.*буст'), 'other',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'boost|буст|продвижен'), 'other',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'return|возврат'), 'returns',
      match(lowerUTF8(trim(concat(service_type, ' ', transaction_type))), 'sale|продаж|платеж покупателя|платёж покупателя'), 'sales',
      'other'
    ) AS category
  FROM raw_ym_finance FINAL
  WHERE event_date >= toDate(now(), 'Europe/Moscow') - %(days)s
)
GROUP BY event_date, account_id;
