-- Revert raw_wb_orders ORDER BY
CREATE TABLE raw_wb_orders_old
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  srid String,
  last_change_ts DateTime,
  event_ts DateTime,
  nm_id UInt64,
  chrt_id UInt64,
  quantity UInt16,
  price_rub Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_ts)
ORDER BY (account_id, srid);

INSERT INTO raw_wb_orders_old SELECT * FROM raw_wb_orders;
DROP TABLE raw_wb_orders;
RENAME TABLE raw_wb_orders_old TO raw_wb_orders;

-- Revert raw_wb_sales ORDER BY
CREATE TABLE raw_wb_sales_old
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
ORDER BY (account_id, srid);

INSERT INTO raw_wb_sales_old SELECT * FROM raw_wb_sales;
DROP TABLE raw_wb_sales;
RENAME TABLE raw_wb_sales_old TO raw_wb_sales;

-- Revert dim_product ORDER BY
CREATE TABLE dim_product_old
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  chrt_id Nullable(UInt64),
  sku Nullable(String),
  offer_id Nullable(String),
  ozon_product_id Nullable(UInt64),
  title Nullable(String),
  brand Nullable(String),
  category Nullable(String),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (marketplace, account_id, product_id);

INSERT INTO dim_product_old SELECT * FROM dim_product;
DROP TABLE dim_product;
RENAME TABLE dim_product_old TO dim_product;
