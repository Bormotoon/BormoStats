-- Raw Yandex Market datasets use snapshot/ingestion versions for idempotent replacement.
CREATE TABLE IF NOT EXISTS raw_ym_orders
(
    run_id UUID,
    account_id String,
    order_id UInt64,
    offer_id String,
    product_id UInt64,
    status LowCardinality(String),
    substatus LowCardinality(String),
    created_at DateTime,
    updated_at DateTime,
    qty UInt32,
    buyer_price Float64,
    seller_price Float64,
    subsidy Float64,
    payload String,
    ingested_at DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, order_id, offer_id);

CREATE TABLE IF NOT EXISTS raw_ym_stocks
(
    run_id UUID,
    account_id String,
    offer_id String,
    product_id UInt64,
    warehouse_id Int64,
    warehouse_name String,
    stock_fit Int64,
    stock_freeze Int64,
    snapshot_ts DateTime,
    payload String
)
ENGINE = ReplacingMergeTree(snapshot_ts)
ORDER BY (account_id, offer_id, warehouse_id, snapshot_ts);

CREATE TABLE IF NOT EXISTS raw_ym_prices
(
    run_id UUID,
    account_id String,
    offer_id String,
    product_id UInt64,
    list_price Float64,
    seller_price Float64,
    cofinance_price Nullable(Float64),
    buyer_price Nullable(Float64),
    name String DEFAULT '',
    purchase_price Float64 DEFAULT 0,
    commission_pct Float64,
    logistics_rub Float64,
    acquiring_rub Float64,
    snapshot_ts DateTime,
    payload String
)
ENGINE = ReplacingMergeTree(snapshot_ts)
ORDER BY (account_id, offer_id);

CREATE TABLE IF NOT EXISTS raw_ym_offer_mappings
(
    run_id UUID,
    account_id String,
    offer_id String,
    market_sku UInt64,
    name String,
    pictures Array(String),
    purchase_price Float64,
    payload String,
    ingested_at DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, offer_id);

CREATE TABLE IF NOT EXISTS raw_ym_funnel
(
    run_id UUID,
    account_id String,
    day Date,
    offer_id String,
    product_id UInt64,
    shows UInt64,
    clicks UInt64,
    to_cart UInt64,
    orders UInt64,
    revenue Float64,
    ingested_at DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, day, product_id);

CREATE TABLE IF NOT EXISTS raw_ym_ads
(
    run_id UUID,
    account_id String,
    day Date,
    campaign_id String,
    offer_id String,
    product_id UInt64,
    impressions UInt64,
    clicks UInt64,
    cost Float64,
    orders UInt64,
    revenue Float64,
    ingested_at DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, day, campaign_id, product_id);

CREATE TABLE IF NOT EXISTS raw_ym_finance
(
    run_id UUID,
    account_id String,
    transaction_id String,
    event_date Date,
    order_id Nullable(UInt64),
    offer_id String,
    transaction_type LowCardinality(String),
    service_type LowCardinality(String),
    amount Float64,
    payout Float64,
    payload String,
    ingested_at DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, event_date, transaction_id);

CREATE TABLE IF NOT EXISTS raw_ym_campaigns
(
    run_id UUID,
    account_id String,
    business_id String,
    campaign_id String,
    campaign_name String,
    business_name String,
    campaign_type LowCardinality(String),
    snapshot_ts DateTime,
    payload String
)
ENGINE = ReplacingMergeTree(snapshot_ts)
ORDER BY (account_id, campaign_id);
