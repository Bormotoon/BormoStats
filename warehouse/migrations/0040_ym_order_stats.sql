-- One latest statistics snapshot per order and SKU; nullable metrics mean not attributable.
CREATE TABLE IF NOT EXISTS raw_ym_order_stats
(
    run_id UUID,
    account_id String,
    order_id UInt64,
    offer_id String,
    product_id UInt64,
    status LowCardinality(String),
    created_at DateTime,
    updated_at DateTime,
    qty UInt32,
    buyer_price Nullable(Float64),
    cashback Nullable(Float64),
    marketplace_discount Nullable(Float64),
    cofinance_value Nullable(Float64),
    fee Nullable(Float64),
    acquiring Nullable(Float64),
    logistics Nullable(Float64),
    payload String,
    ingested_at DateTime
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, order_id, offer_id);
