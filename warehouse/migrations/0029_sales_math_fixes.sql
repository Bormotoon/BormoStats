-- Sales, stock and time fixes. After applying, rebuild the derived layers:
--   POST /api/v1/admin/transforms/backfill {"days": 730}
--   POST /api/v1/admin/backfill {"marketplace": "marts", "dataset": "build", "days": 730}
-- and re-collect WB sales (POST /api/v1/admin/backfill wb/sales 90 days) to restore sales
-- that a later return had replaced.

-- 1. raw_wb_sales: a sale (saleID S…) and its return (R…) share srid/nm_id/chrt_id, so the
--    return replaced the sale. sale_id joins the key; price/payout/return flag are re-read
--    from the payload (price was forPay, payout was incomeID — the supply number).
CREATE TABLE IF NOT EXISTS raw_wb_sales_v29
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  srid String,
  sale_id String DEFAULT '',
  last_change_ts DateTime,
  event_ts DateTime,
  nm_id UInt64,
  chrt_id UInt64,
  barcode Nullable(String),
  quantity UInt16,
  price_rub Float64,
  payout_rub Nullable(Float64),
  is_return UInt8,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_ts)
ORDER BY (account_id, srid, nm_id, chrt_id, sale_id);

-- a re-run after the EXCHANGE below must not swap the old table back in
TRUNCATE TABLE raw_wb_sales_v29;

-- every stored version, not FINAL: unmerged parts still hold sales their return replaced
INSERT INTO raw_wb_sales_v29
SELECT
  ingested_at,
  run_id,
  account_id,
  srid,
  JSONExtractString(payload, 'saleID') AS sale_id,
  last_change_ts,
  event_ts,
  nm_id,
  chrt_id,
  barcode,
  quantity,
  abs(if(JSONExtractFloat(payload, 'priceWithDisc') != 0,
         JSONExtractFloat(payload, 'priceWithDisc'),
         JSONExtractFloat(payload, 'totalPrice'))) AS price_rub,
  if(ret = 1, -abs(JSONExtractFloat(payload, 'forPay')), JSONExtractFloat(payload, 'forPay')) AS payout_rub,
  ret AS is_return,
  payload
FROM
(
  SELECT
    *,
    if(
      startsWith(upper(JSONExtractString(payload, 'saleID')), 'R')
      OR JSONExtractFloat(payload, 'priceWithDisc') < 0
      OR JSONExtractFloat(payload, 'forPay') < 0
      OR is_return = 1,
      1, 0
    ) AS ret
  FROM raw_wb_sales
);

EXCHANGE TABLES raw_wb_sales AND raw_wb_sales_v29;
DROP TABLE IF EXISTS raw_wb_sales_v29;

-- 2. raw_wb_orders: the order value was totalPrice (list price before every discount).
ALTER TABLE raw_wb_orders
  UPDATE price_rub = JSONExtractFloat(payload, 'priceWithDisc')
  WHERE JSONExtractFloat(payload, 'priceWithDisc') > 0
    AND price_rub != JSONExtractFloat(payload, 'priceWithDisc');

-- 3. raw_ozon_posting_items: rows collected before postings carried the SKU were stored with
--    ozon_product_id = 0 and were counted a second time next to the re-collected SKU rows.
ALTER TABLE raw_ozon_posting_items
  DELETE WHERE ozon_product_id = 0
    AND posting_number IN (
      SELECT posting_number FROM raw_ozon_posting_items WHERE ozon_product_id != 0
    );

-- 4. raw_ozon_stocks: Ozon reports negative ids for some FBO warehouses, so every snapshot
--    failed on the UInt64 column and no Ozon stock was ever stored (the table is empty).
DROP TABLE IF EXISTS raw_ozon_stocks;
CREATE TABLE IF NOT EXISTS raw_ozon_stocks
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  snapshot_ts DateTime,
  ozon_product_id UInt64,
  offer_id Nullable(String),
  warehouse_id Nullable(Int64),
  present Int32,
  reserved Int32,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (account_id, snapshot_ts, ozon_product_id, warehouse_id)
SETTINGS allow_nullable_key = 1;

-- 5. Staging tables are derived from raw and rebuilt by the transform backfill. The business
--    day is the Moscow day, as in the marketplaces' own reports, instead of the server's
--    time zone; event times are true instants (see docs/data_catalog.md, "Time").
DROP TABLE IF EXISTS stg_sales;
CREATE TABLE IF NOT EXISTS stg_sales
(
  event_ts DateTime,
  day Date MATERIALIZED toDate(event_ts, 'Europe/Moscow'),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  order_id String,
  posting_number Nullable(String),
  srid Nullable(String),
  product_id String,
  nm_id Nullable(UInt64),
  ozon_product_id Nullable(UInt64),
  offer_id Nullable(String),
  qty Int32,
  price_gross Float64,
  payout Nullable(Float64),
  is_return UInt8,
  last_change_ts Nullable(DateTime),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, order_id, product_id, event_ts);

DROP TABLE IF EXISTS stg_orders;
CREATE TABLE IF NOT EXISTS stg_orders
(
  event_ts DateTime,
  day Date MATERIALIZED toDate(event_ts, 'Europe/Moscow'),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  order_id String,
  status LowCardinality(String),
  product_id Nullable(String),
  qty Nullable(Int32),
  price_gross Nullable(Float64),
  last_change_ts Nullable(DateTime),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, order_id, event_ts);

DROP TABLE IF EXISTS stg_stocks;
CREATE TABLE IF NOT EXISTS stg_stocks
(
  snapshot_ts DateTime,
  day Date MATERIALIZED toDate(snapshot_ts, 'Europe/Moscow'),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  ozon_product_id Nullable(UInt64),
  offer_id Nullable(String),
  warehouse_id Nullable(Int64),
  amount Int32,
  reserved Nullable(Int32),
  present Nullable(Int32),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id, warehouse_id)
SETTINGS allow_nullable_key = 1;

DROP TABLE IF EXISTS mrt_stock_daily;
CREATE TABLE IF NOT EXISTS mrt_stock_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  warehouse_id Nullable(Int64),
  stock_end Int64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id, warehouse_id)
SETTINGS allow_nullable_key = 1;

-- 6. KPI views: read the marts FINAL (a rebuild leaves the previous rows until the
--    delete finishes) and cover exactly 30 Moscow days including today.
CREATE OR REPLACE VIEW v_kpi_sales_30d AS
SELECT
  marketplace,
  account_id,
  sum(revenue) AS revenue_30d,
  sum(qty) AS qty_30d,
  sum(returns_qty) AS returns_30d
FROM mrt_sales_daily FINAL
WHERE day > toDate(now(), 'Europe/Moscow') - 30
GROUP BY marketplace, account_id;

CREATE OR REPLACE VIEW v_kpi_ads_30d AS
SELECT
  marketplace,
  account_id,
  sum(cost) AS cost_30d,
  sum(revenue) AS revenue_30d,
  if(sum(revenue) = 0, 0, sum(cost) / sum(revenue)) AS acos_30d
FROM mrt_ads_daily FINAL
WHERE day > toDate(now(), 'Europe/Moscow') - 30
GROUP BY marketplace, account_id;
