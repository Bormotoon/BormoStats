USE mp_analytics;

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

CREATE TABLE IF NOT EXISTS stg_funnel_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  nm_id Nullable(UInt64),
  views UInt64,
  adds_to_cart UInt64,
  orders UInt64,
  orders_sum Float64,
  buyouts UInt64,
  cancels UInt64,
  add_to_cart_conv Float64,
  cart_to_order_conv Float64,
  buyout_percent Float64,
  wishlist UInt64,
  currency LowCardinality(String),
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id);

CREATE TABLE IF NOT EXISTS stg_ads_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  campaign_id String,
  impressions UInt64,
  clicks UInt64,
  cost Float64,
  orders UInt64,
  revenue Float64,
  meta_json String,
  ingested_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, campaign_id);
