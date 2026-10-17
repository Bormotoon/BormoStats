-- Pricing: cost price by supplier article, price-keeping rules and the current price breakdown.

-- Cost price of a supplier article (WB vendorCode, Ozon offer_id) within an organization; one
-- value for every marketplace the article is sold on. Replaces the platform-level
-- dim_product_cost, which stays as a fallback for marts.
CREATE TABLE IF NOT EXISTS dim_offer_cost
(
  organization_id LowCardinality(String),
  offer_id String,
  cost_price_rub Float64,
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (organization_id, offer_id);

-- Price rules now name the product by supplier article (product_id = offer_id) and say what to
-- keep: 'buyer_price' (the price the buyer pays after the marketplace's discount),
-- 'seller_price' (the seller's price after the seller's discount) or 'margin' (break-even plus
-- target_margin_percent). target_price is the price to keep; max_step_pct caps one change.
ALTER TABLE dim_price_rule ADD COLUMN IF NOT EXISTS mode LowCardinality(String) DEFAULT 'margin';
ALTER TABLE dim_price_rule ADD COLUMN IF NOT EXISTS target_price Float64 DEFAULT 0;
ALTER TABLE dim_price_rule ADD COLUMN IF NOT EXISTS max_step_pct Float64 DEFAULT 10;

-- Current price breakdown per card, rebuilt whole with every mart run
-- (workers/app/sql/marts/mrt_price_current.sql). Percentages are 0..100.
CREATE TABLE IF NOT EXISTS mrt_price_current
(
  marketplace LowCardinality(String),
  account_id LowCardinality(String),
  offer_id String,
  product_id String,
  ozon_product_id Nullable(UInt64),
  title Nullable(String),
  image_url Nullable(String),
  list_price Float64,
  seller_discount_pct Float64,
  seller_price Float64,
  mp_discount_pct Nullable(Float64),
  mp_discount_scope LowCardinality(String),
  mp_discount_samples UInt32,
  buyer_price Nullable(Float64),
  commission_pct Float64,
  commission_rub Float64,
  acquiring_rub Float64,
  logistics_rub Float64,
  fees_rub Float64,
  cost_price Nullable(Float64),
  margin_rub Nullable(Float64),
  margin_pct Nullable(Float64),
  breakeven_price Nullable(Float64),
  min_price Nullable(Float64),
  auto_actions_enabled Nullable(UInt8),
  price_seen_at DateTime,
  built_at DateTime
)
ENGINE = ReplacingMergeTree(built_at)
ORDER BY (marketplace, account_id, offer_id);

-- Article cost price spread onto the products marts are keyed by (WB nmID, Ozon SKU): every
-- card of the account whose supplier article has a cost in the account's organization.
CREATE VIEW IF NOT EXISTS v_offer_cost AS
SELECT
  p.marketplace AS marketplace,
  p.account_id AS account_id,
  p.product_id AS product_id,
  any(c.cost_price_rub) AS cost_price_rub
FROM
(
  SELECT DISTINCT marketplace, account_id, product_id, assumeNotNull(offer_id) AS offer_id
  FROM dim_product FINAL
  WHERE ifNull(offer_id, '') != ''
) AS p
INNER JOIN (SELECT marketplace, account_id, organization_id FROM dim_account FINAL) AS a
  ON a.marketplace = p.marketplace AND a.account_id = p.account_id
INNER JOIN (SELECT organization_id, offer_id, cost_price_rub FROM dim_offer_cost FINAL) AS c
  ON c.organization_id = a.organization_id AND c.offer_id = p.offer_id
GROUP BY p.marketplace, p.account_id, p.product_id;
