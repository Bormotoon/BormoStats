-- Preserve the observed delivered state when a later order snapshot is returned.
CREATE TABLE IF NOT EXISTS raw_ym_delivered_snapshots AS raw_ym_orders
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (account_id, order_id, offer_id, updated_at);
