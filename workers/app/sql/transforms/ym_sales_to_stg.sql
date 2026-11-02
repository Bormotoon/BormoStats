-- Keep a previously observed delivery after subsequent return snapshots replace raw orders.
INSERT INTO stg_sales
(event_ts, marketplace, account_id, order_id, posting_number, srid, product_id, nm_id, ozon_product_id,
 offer_id, qty, price_gross, payout, is_return, last_change_ts, meta_json, ingested_at)
WITH deliveries AS
(
    SELECT account_id, order_id, offer_id,
      argMin(product_id, updated_at) AS product_id, argMin(qty, updated_at) AS qty,
      argMin(seller_price, updated_at) AS seller_price, min(updated_at) AS delivered_at,
      argMin(payload, updated_at) AS payload
    FROM
    (
      SELECT account_id, order_id, offer_id, product_id, qty, seller_price, updated_at, payload
      FROM raw_ym_delivered_snapshots FINAL
      UNION ALL
      SELECT account_id, order_id, offer_id, product_id, qty, seller_price, updated_at, payload
      FROM raw_ym_orders FINAL WHERE status = 'DELIVERED'
    )
    GROUP BY account_id, order_id, offer_id
), returns AS
(
    SELECT s.account_id AS account_id, s.order_id AS order_id, s.offer_id AS offer_id,
      s.product_id AS product_id, s.updated_at AS updated_at, s.payload AS payload,
      arrayJoin(JSONExtractArrayRaw(s.payload, 'item', 'details')) AS detail,
      JSONExtractInt(detail, 'itemCount') AS return_qty,
      coalesce(parseDateTimeBestEffortOrNull(JSONExtractString(detail, 'updateDate')), s.updated_at) AS return_ts,
      coalesce(nullIf(d.seller_price, 0), nullIf(o.seller_price, 0)) AS seller_price
    FROM raw_ym_order_stats AS s FINAL
    LEFT JOIN deliveries AS d ON d.account_id = s.account_id AND d.order_id = s.order_id AND d.offer_id = s.offer_id
    LEFT JOIN raw_ym_orders AS o FINAL ON o.account_id = s.account_id AND o.order_id = s.order_id AND o.offer_id = s.offer_id
    WHERE s.status IN ('PARTIALLY_RETURNED', 'RETURNED')
      AND JSONExtractString(detail, 'itemStatus') = 'RETURNED'
)
SELECT delivered_at, 'ym', account_id, toString(order_id), NULL, NULL, toString(product_id), product_id,
  NULL, offer_id, toInt32(qty), seller_price, seller_price * qty, toUInt8(0),
  delivered_at, payload, now()
FROM deliveries
WHERE delivered_at >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(delivered_at, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
UNION ALL
SELECT return_ts + INTERVAL 1 SECOND, 'ym', account_id, toString(order_id), NULL, NULL,
  toString(product_id), product_id, NULL, offer_id, -toInt32(sum(return_qty)), any(seller_price),
  -any(seller_price) * sum(return_qty), toUInt8(1), max(updated_at), any(payload), now()
FROM returns
WHERE return_qty > 0 AND seller_price IS NOT NULL
  AND return_ts >= now() - toIntervalDay(%(days)s + 2)
  AND toDate(return_ts, 'Europe/Moscow') >= toDate(now(), 'Europe/Moscow') - %(days)s
GROUP BY account_id, order_id, offer_id, product_id, return_ts;
