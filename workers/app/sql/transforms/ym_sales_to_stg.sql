-- Keep a previously observed delivery after subsequent return snapshots replace raw orders,
-- or recover the delivery from confirmed buyer-payment rows in raw_ym_finance when an order
-- was first imported already in PARTIALLY_RETURNED / RETURNED state.
INSERT INTO stg_sales
(event_ts, marketplace, account_id, order_id, posting_number, srid, product_id, nm_id, ozon_product_id,
 offer_id, qty, price_gross, payout, is_return, last_change_ts, meta_json, ingested_at)
WITH mappings AS
(
    SELECT account_id, offer_id, market_sku
    FROM raw_ym_offer_mappings FINAL
    WHERE market_sku > 0
), deliveries AS
(
    SELECT account_id, order_id, offer_id,
      argMin(product_id, (priority, updated_at)) AS product_id,
      argMin(qty, (priority, updated_at)) AS qty,
      argMin(seller_price, (priority, updated_at)) AS seller_price,
      argMin(updated_at, (priority, updated_at)) AS delivered_at,
      argMin(payload, (priority, updated_at)) AS payload
    FROM
    (
      SELECT account_id, order_id, offer_id, product_id, qty, seller_price, updated_at, payload, 1 AS priority
      FROM raw_ym_delivered_snapshots FINAL
      UNION ALL
      SELECT account_id, order_id, offer_id, product_id, qty, seller_price, updated_at, payload, 1 AS priority
      FROM raw_ym_orders FINAL WHERE status = 'DELIVERED'
      UNION ALL
      SELECT o.account_id AS account_id, o.order_id AS order_id, o.offer_id AS offer_id,
        o.product_id AS product_id, o.qty AS qty,
        if(o.seller_price > 0, o.seller_price, f.sale_amount / greatest(o.qty, 1)) AS seller_price,
        f.delivered_at AS updated_at,
        concat(char(123), '"source_quality":"recovered_from_finance","raw":', o.payload, char(125)) AS payload,
        2 AS priority
      FROM raw_ym_orders AS o FINAL
      INNER JOIN
      (
        SELECT account_id, assumeNotNull(order_id) AS order_id, offer_id,
          toDateTime(min(event_date), 'Europe/Moscow') AS delivered_at,
          sum(amount) AS sale_amount
        FROM raw_ym_finance FINAL
        WHERE order_id IS NOT NULL
          AND amount > 0
          AND match(
            lowerUTF8(concat(transaction_type, ' ', service_type)),
            'payment|платеж|revenue|sales|платеж покупателя'
          )
        GROUP BY account_id, order_id, offer_id
      ) AS f ON f.account_id = o.account_id AND f.order_id = o.order_id AND f.offer_id = o.offer_id
      WHERE o.status IN ('PARTIALLY_RETURNED', 'RETURNED')
    )
    GROUP BY account_id, order_id, offer_id
), returns AS
(
    SELECT s.account_id AS account_id, s.order_id AS order_id, s.offer_id AS offer_id,
      if(m.market_sku > 0, m.market_sku, s.product_id) AS product_id,
      s.updated_at AS updated_at,
      if(
        d.order_id > 0,
        s.payload,
        concat(char(123), '"source_quality":"return_without_observed_delivery","raw":', s.payload, char(125))
      ) AS payload,
      arrayJoin(JSONExtractArrayRaw(s.payload, 'item', 'details')) AS detail,
      JSONExtractInt(detail, 'itemCount') AS return_qty,
      coalesce(parseDateTimeBestEffortOrNull(JSONExtractString(detail, 'updateDate')), s.updated_at) AS return_ts,
      coalesce(nullIf(d.seller_price, 0), nullIf(o.seller_price, 0)) AS seller_price
    FROM raw_ym_order_stats AS s FINAL
    LEFT JOIN deliveries AS d ON d.account_id = s.account_id AND d.order_id = s.order_id AND d.offer_id = s.offer_id
    LEFT JOIN raw_ym_orders AS o FINAL ON o.account_id = s.account_id AND o.order_id = s.order_id AND o.offer_id = s.offer_id
    LEFT JOIN mappings AS m ON m.account_id = s.account_id AND m.offer_id = s.offer_id
    WHERE s.status IN ('PARTIALLY_RETURNED', 'RETURNED')
      AND JSONExtractString(detail, 'itemStatus') = 'RETURNED'
)
SELECT d.delivered_at, 'ym', d.account_id, toString(d.order_id), NULL, NULL,
  toString(if(m.market_sku > 0, m.market_sku, d.product_id)),
  if(m.market_sku > 0, m.market_sku, d.product_id),
  NULL, d.offer_id, toInt32(d.qty), d.seller_price, d.seller_price * d.qty, toUInt8(0),
  d.delivered_at, d.payload, now()
FROM deliveries AS d
LEFT JOIN mappings AS m ON m.account_id = d.account_id AND m.offer_id = d.offer_id
WHERE d.delivered_at >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(d.delivered_at, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
UNION ALL
SELECT return_ts + INTERVAL 1 SECOND, 'ym', account_id, toString(order_id), NULL, NULL,
  toString(product_id), product_id, NULL, offer_id, -toInt32(sum(return_qty)), any(seller_price),
  -any(seller_price) * sum(return_qty), toUInt8(1), max(updated_at), any(payload), now()
FROM returns
WHERE return_qty > 0 AND seller_price IS NOT NULL
  AND return_ts >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(return_ts, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
GROUP BY account_id, order_id, offer_id, product_id, return_ts;
