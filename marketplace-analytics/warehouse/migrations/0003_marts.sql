USE mp_analytics;

CREATE TABLE IF NOT EXISTS mrt_sales_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  qty Int64,
  revenue Float64,
  payout Nullable(Float64),
  returns_qty Int64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id);

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
ORDER BY (marketplace, account_id, day, product_id, warehouse_id);

CREATE TABLE IF NOT EXISTS mrt_funnel_daily
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  views UInt64,
  adds_to_cart UInt64,
  orders UInt64,
  cr_order Float64,
  cr_cart Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, product_id);

CREATE TABLE IF NOT EXISTS mrt_ads_daily
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
  acos Float64,
  romi Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (marketplace, account_id, day, campaign_id);

CREATE VIEW IF NOT EXISTS v_kpi_sales_30d AS
SELECT
  marketplace,
  account_id,
  sum(revenue) AS revenue_30d,
  sum(qty) AS qty_30d,
  sum(returns_qty) AS returns_30d
FROM mrt_sales_daily
WHERE day >= today() - 30
GROUP BY marketplace, account_id;

CREATE VIEW IF NOT EXISTS v_kpi_ads_30d AS
SELECT
  marketplace,
  account_id,
  sum(cost) AS cost_30d,
  sum(revenue) AS revenue_30d,
  if(sum(revenue)=0, 0, sum(cost)/sum(revenue)) AS acos_30d
FROM mrt_ads_daily
WHERE day >= today() - 30
GROUP BY marketplace, account_id;
