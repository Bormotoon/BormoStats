CREATE TABLE IF NOT EXISTS raw_ym_tariff_quotes
(
    run_id UUID,
    account_id String,
    offer_id String,
    price Float64,
    fee Nullable(Float64),
    acquiring Nullable(Float64),
    logistics Nullable(Float64),
    payload String,
    snapshot_ts DateTime
)
ENGINE = ReplacingMergeTree(snapshot_ts)
ORDER BY (account_id, offer_id);
