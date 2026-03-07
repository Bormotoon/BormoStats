-- SYS
CREATE TABLE IF NOT EXISTS sys_schema_migrations
(
  version String,
  applied_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (version);

CREATE TABLE IF NOT EXISTS sys_watermarks
(
  source LowCardinality(String),
  account_id LowCardinality(String),
  watermark_ts DateTime,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (source, account_id);

CREATE TABLE IF NOT EXISTS sys_task_runs
(
  task_name LowCardinality(String),
  run_id UUID,
  started_at DateTime,
  finished_at DateTime,
  status LowCardinality(String),
  rows_ingested UInt64,
  message String,
  meta_json String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(started_at)
ORDER BY (task_name, started_at, run_id);

-- DIMS
CREATE TABLE IF NOT EXISTS dim_marketplace
(
  marketplace LowCardinality(String),
  title String
)
ENGINE = TinyLog;

INSERT INTO dim_marketplace (marketplace, title)
SELECT *
FROM (
  SELECT 'wb' AS marketplace, 'Wildberries' AS title
  UNION ALL
  SELECT 'ozon' AS marketplace, 'Ozon' AS title
);

CREATE TABLE IF NOT EXISTS dim_account
(
  account_id LowCardinality(String),
  marketplace LowCardinality(String),
  title String,
  created_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (marketplace, account_id);

INSERT INTO dim_account (account_id, marketplace, title)
SELECT *
FROM (
  SELECT 'default' AS account_id, 'wb' AS marketplace, 'WB default' AS title
  UNION ALL
  SELECT 'default' AS account_id, 'ozon' AS marketplace, 'Ozon default' AS title
);

CREATE TABLE IF NOT EXISTS dim_product
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

-- RAW WB
CREATE TABLE IF NOT EXISTS raw_wb_sales
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

CREATE TABLE IF NOT EXISTS raw_wb_orders
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

CREATE TABLE IF NOT EXISTS raw_wb_stocks
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  snapshot_ts DateTime,
  nm_id Nullable(UInt64),
  chrt_id UInt64,
  sku Nullable(String),
  warehouse_id Nullable(UInt64),
  amount Int32,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (account_id, snapshot_ts, chrt_id);

CREATE TABLE IF NOT EXISTS raw_wb_funnel_daily
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  nm_id UInt64,
  open_card_count UInt64,
  add_to_cart_count UInt64,
  orders_count UInt64,
  orders_sum_rub Float64,
  buyouts_count UInt64,
  buyouts_sum_rub Float64,
  cancel_count UInt64,
  cancel_sum_rub Float64,
  add_to_cart_conv Float64,
  cart_to_order_conv Float64,
  buyout_percent Float64,
  add_to_wishlist UInt64,
  currency LowCardinality(String),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, nm_id);

-- RAW OZON
CREATE TABLE IF NOT EXISTS raw_ozon_postings
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  posting_number String,
  status LowCardinality(String),
  created_at DateTime,
  in_process_at Nullable(DateTime),
  shipped_at Nullable(DateTime),
  delivered_at Nullable(DateTime),
  canceled_at Nullable(DateTime),
  ozon_warehouse_id Nullable(UInt64),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (account_id, posting_number);

CREATE TABLE IF NOT EXISTS raw_ozon_posting_items
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  posting_number String,
  ozon_product_id UInt64,
  offer_id Nullable(String),
  name Nullable(String),
  quantity UInt16,
  price Float64,
  payout Nullable(Float64),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(ingested_at)
ORDER BY (account_id, posting_number, ozon_product_id);

CREATE TABLE IF NOT EXISTS raw_ozon_stocks
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

CREATE TABLE IF NOT EXISTS raw_ozon_ads_daily
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  day Date,
  campaign_id String,
  impressions UInt64,
  clicks UInt64,
  cost Float64,
  orders UInt64,
  revenue Float64,
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (account_id, day, campaign_id);

CREATE TABLE IF NOT EXISTS raw_ozon_finance_ops
(
  ingested_at DateTime DEFAULT now(),
  run_id UUID,
  account_id LowCardinality(String),
  operation_id String,
  operation_ts DateTime,
  type LowCardinality(String),
  amount Float64,
  currency LowCardinality(String),
  payload String
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(operation_ts)
ORDER BY (account_id, operation_ts, operation_id);
