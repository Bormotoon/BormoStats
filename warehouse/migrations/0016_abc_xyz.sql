-- ABC/XYZ analysis

CREATE TABLE IF NOT EXISTS mrt_abc_xyz_analysis
(
  day Date,
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  product_id String,
  revenue_60d Float64,
  share_pct Float32,
  cumulative_share_pct Float32,
  abc_class Enum8('A' = 1, 'B' = 2, 'C' = 3),
  daily_mean_qty Float64,
  daily_stddev_qty Float64,
  cv_pct Float32,
  xyz_class Enum8('X' = 1, 'Y' = 2, 'Z' = 3),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(day)
ORDER BY (day, marketplace, account_id, product_id);
