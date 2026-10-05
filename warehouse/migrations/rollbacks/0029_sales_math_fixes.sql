-- Revert 0029. Not restored: the duplicate ozon_product_id = 0 posting items (they double
-- counted revenue) and the recomputed raw_wb_sales / raw_wb_orders prices. Rebuild the
-- derived layers afterwards (transform and marts backfill).

-- raw_wb_sales back to the key without sale_id (a return collapses its sale again)
CREATE TABLE IF NOT EXISTS raw_wb_sales_r29
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  srid String,
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
ORDER BY (account_id, srid, nm_id, chrt_id);

TRUNCATE TABLE raw_wb_sales_r29;

INSERT INTO raw_wb_sales_r29
SELECT
  ingested_at, run_id, account_id, srid, last_change_ts, event_ts, nm_id, chrt_id, barcode,
  quantity, price_rub, payout_rub, is_return, payload
FROM raw_wb_sales;

EXCHANGE TABLES raw_wb_sales AND raw_wb_sales_r29;
DROP TABLE IF EXISTS raw_wb_sales_r29;

-- raw_ozon_stocks back to UInt64 warehouses; rows of negative-id warehouses are dropped
CREATE TABLE IF NOT EXISTS raw_ozon_stocks_r29
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  snapshot_ts DateTime,
  ozon_product_id UInt64,
  offer_id Nullable(String),
  warehouse_id Nullable(UInt64),
  present Int32,
  reserved Int32,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (account_id, snapshot_ts, ozon_product_id, warehouse_id)
SETTINGS allow_nullable_key = 1;

TRUNCATE TABLE raw_ozon_stocks_r29;

INSERT INTO raw_ozon_stocks_r29
SELECT
  ingested_at, run_id, account_id, snapshot_ts, ozon_product_id, offer_id,
  toUInt64OrNull(toString(warehouse_id)), present, reserved, payload
FROM raw_ozon_stocks
WHERE warehouse_id IS NULL OR warehouse_id >= 0;

EXCHANGE TABLES raw_ozon_stocks AND raw_ozon_stocks_r29;
DROP TABLE IF EXISTS raw_ozon_stocks_r29;

-- staging and the stock mart with the server-time-zone day (derived, rebuilt afterwards)
DROP TABLE IF EXISTS stg_sales;
CREATE TABLE IF NOT EXISTS stg_sales
(
  event_ts DateTime,
  day Date MATERIALIZED toDate(event_ts),
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
  day Date MATERIALIZED toDate(event_ts),
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
  day Date MATERIALIZED toDate(snapshot_ts),
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  ozon_product_id Nullable(UInt64),
  offer_id Nullable(String),
  warehouse_id Nullable(UInt64),
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
  warehouse_id Nullable(UInt64),
  stock_end Int64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id, warehouse_id)
SETTINGS allow_nullable_key = 1;

CREATE OR REPLACE VIEW v_kpi_sales_30d AS
SELECT
  marketplace,
  account_id,
  sum(revenue) AS revenue_30d,
  sum(qty) AS qty_30d,
  sum(returns_qty) AS returns_30d
FROM mrt_sales_daily
WHERE day >= today() - 30
GROUP BY marketplace, account_id;

CREATE OR REPLACE VIEW v_kpi_ads_30d AS
SELECT
  marketplace,
  account_id,
  sum(cost) AS cost_30d,
  sum(revenue) AS revenue_30d,
  if(sum(revenue) = 0, 0, sum(cost) / sum(revenue)) AS acos_30d
FROM mrt_ads_daily
WHERE day >= today() - 30
GROUP BY marketplace, account_id;
